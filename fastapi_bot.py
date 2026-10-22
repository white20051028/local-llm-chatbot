"""FastAPI 后端：流式对话接口。

一次请求要过三道关，顺序很重要：

    ① 鉴权  dependencies=[Depends(require_api_key)]   → 失败 401
    ② 校验  payload: ChatRequest                      → 失败 422
    ③ 业务  裁剪历史、调模型、流式返回                 → 失败 500

为什么是这个顺序：FastAPI 先解依赖、再验证请求体、最后才进函数。
所以"key 错了"永远看到 401、"body 错了但 key 对"才看到 422。
"""

import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_openai import ChatOpenAI

from auth import require_api_key
from schemas import ChatRequest

# 加载环境变量。必须在任何 os.getenv 之前执行。
load_dotenv()

# 用文件所在目录作为基准，这样不管从哪个目录启动都能找到 static/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# docs_url / redoc_url 都设成 None，是因为下面要自己写 /docs 路由。
#
# 为什么必须自己写：
#   ① FastAPI 0.143 已经**移除**了 swagger_js_url / swagger_css_url 这两个参数。
#      而 FastAPI.__init__ 带 **extra，所以传进去既不报错、也不生效——
#      默认仍然指向 cdn.jsdelivr.net。
#   ② 那个域名在国内基本连不上，于是 /docs 的 HTML 能返回 200，
#      但 Swagger 的 JS 永远加载不到，页面一片白。
#   ③ 把资源放进本地 static/ 之后，断网也能打开文档，面试演示不怕网络出问题。
app = FastAPI(
    title="本地对话机器人 API",
    description="带鉴权的流式对话接口。所有 /chat 请求需要在 Header 里带上 X-API-Key。",
    docs_url=None,
    redoc_url=None,
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 把 static/ 挂到 /static 下，供 /docs 页面加载本地的 swagger 资源
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    """自定义的接口文档页，资源全部走本地 /static，不依赖任何 CDN。"""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - 接口文档",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="",
    )


@app.get("/", include_in_schema=False)
async def root():
    """访问根路径直接跳到文档页，省得看到 {"detail":"Not Found"}。"""
    return RedirectResponse(url="/docs")


@app.exception_handler(RequestValidationError)
async def on_request_validation_error(request: Request, exc: RequestValidationError):
    """把 Pydantic 的报错压成 [{"field": ..., "reason": ...}]。

    默认结构长这样：
        {"detail":[{"type":"less_than_equal","loc":["body","temperature"],
                    "msg":"Input should be less than or equal to 2",
                    "input":9,"ctx":{"le":2.0}}]}

    字段名埋在三层嵌套里，调用方得自己挖。压平之后一眼就能看到是 temperature 错了。
    注意 loc 的第一段是 "body"，它只说明"这个错误来自请求体"，是噪音，丢掉。
    """
    details = []
    for err in exc.errors():
        loc = err.get("loc", ())
        # ("body", "history", 0, "role")  →  "history.0.role"
        field = ".".join(str(item) for item in loc[1:]) or "body"
        details.append({"field": field, "reason": err.get("msg", "")})
    return JSONResponse(status_code=422, content={"detail": details})


# 三个必需的环境变量，缺任何一个都调不动模型。
MODEL_ENV_KEYS = ("SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL", "SILICONFLOW_MODEL")

_model: ChatOpenAI | None = None


def get_model() -> ChatOpenAI:
    """懒加载模型客户端：第一次真正要用的时候才创建。

    为什么不写成模块级的 `chat_model = ChatOpenAI(...)`：

    ① 模块级写法在 import 阶段就会执行。只要 .env 少配一个变量，
       它会在启动时抛 pydantic 的 ValidationError：
           model
             Input should be a valid string [input_value=None]
       服务直接起不来，而且这行报错完全看不出是"你忘了填 .env"。

    ② 作为 FastAPI 依赖，测试里可以用 app.dependency_overrides 换成假模型，
       一个请求都不会发到网上，也不花钱。
    """
    global _model
    if _model is None:
        missing = [key for key in MODEL_ENV_KEYS if not os.getenv(key)]
        if missing:
            # 说人话的 500：把"缺哪个变量"直接写在响应里，
            # 排查时间从半小时变成十秒。
            raise HTTPException(
                status_code=500,
                detail=f"服务端缺少配置：{', '.join(missing)}，请检查 .env 后重启服务",
            )
        connect_timeout = float(os.getenv("LLM_CONNECT_TIMEOUT", "5"))
        read_timeout = float(os.getenv("LLM_READ_TIMEOUT", "15"))
        _model = ChatOpenAI(
            api_key=os.getenv("SILICONFLOW_API_KEY"),
            base_url=os.getenv("SILICONFLOW_BASE_URL"),
            model=os.getenv("SILICONFLOW_MODEL"),
            request_timeout=(connect_timeout, read_timeout), # 元组是(连接，读取)、
            max_retries=0, # 关掉底层的隐式重试
        )
    return _model


@app.get("/health", summary="健康检查（无需鉴权）")
async def health():
    """探活接口，供部署脚本/负载均衡使用，故意不挂鉴权。"""
    return {"status": "ok"}


@app.post("/chat", summary="流式对话接口", dependencies=[Depends(require_api_key)])
async def chat(payload: ChatRequest, model: ChatOpenAI = Depends(get_model)):
    # 1. 按轮数裁剪历史。history_len=0 表示一条历史都不带。
    #    原代码写的是 `if history_len > 0 and len(history) > history_len*2`，
    #    history_len=0 时整个条件为假、直接跳过裁剪，反而把全部历史都带上了，
    #    与界面上"0 = 不保留"的语义正好相反。这里换成"先算要留几条"。
    keep = payload.history_len * 2
    history = payload.history[-keep:] if keep > 0 else []

    # 2. 组装消息列表。
    #    history 里的 role 已经被 ChatMessage 限制成 user/assistant，
    #    不会有调用方伪造的 system 指令混进来。
    #    content 也已经在 schemas 里归一化成了字符串，这里直接 model_dump。
    messages = [{"role": "system", "content": payload.sys_prompt}]
    messages.extend(msg.model_dump() for msg in history)
    messages.append({"role": "user", "content": payload.query})

    # 3. 绑定本次请求的采样参数
    bound = model.bind(
        temperature=payload.temperature,
        top_p=payload.top_p,
        max_tokens=payload.max_tokens,
    )

    # 4. 异步流式生成
    async def generate_response():
        async for chunk in bound.astream(messages):
            if chunk.content:
                yield chunk.content

    # charset 要显式写：只写 text/plain 时，某些客户端会按 latin-1 解码，中文变乱码。
    return StreamingResponse(
        generate_response(),
        media_type="text/plain; charset=utf-8",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=6066, log_level="info")
