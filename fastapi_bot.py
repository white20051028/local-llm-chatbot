"""FastAPI 后端：流式对话接口。

本 PR（feat/production-ready）做了四件事：

1. 请求体改用 Pydantic 模型（schemas.py）—— 非法请求在进入函数前就返回 422；
2. 加 API Key 鉴权（auth.py）—— 只有带正确 X-API-Key 头的请求才放行；
3. 顺手修掉一个 bug：原来 history_len=0（滑块最左=不保留历史）时，
   条件 `if history_len > 0 and ...` 不成立，反而把**全部**历史都带上了，
   与界面上"0 = 不保留"的语义相反；
4. 把 Swagger 资源本地化到 static/，让 /docs 不再依赖 jsdelivr
   （原因见下面 app = FastAPI(...) 上方的注释）。
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
#   ③ 把资源放进本地 static/ 之后，断网也能打开文档，演示时不怕网络出问题。
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


# 懒加载的模型客户端。
# 不放在模块顶层直接构造，有两个原因：
#   ① 没配 SILICONFLOW_API_KEY 时服务依然能启动（/health 可用、报错更清楚）；
#   ② 测试里可以把它换成假模型，不产生真实网络请求、不花钱。
_model: ChatOpenAI | None = None

# 三个必需的环境变量。缺任何一个都不能正常调用模型。
MODEL_ENV_KEYS = ("SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL", "SILICONFLOW_MODEL")


def get_model() -> ChatOpenAI:
    """返回全局唯一的模型客户端（第一次调用时创建）。

    这里要显式检查配置，而不是直接把 None 交给 ChatOpenAI：
    少了配置时它抛的是 pydantic 的 ValidationError，日志里只有
    "model Input should be a valid string"，完全看不出是 .env 没填。
    换成一个说人话的 500，排查时间从半小时变成十秒。
    """
    global _model
    if _model is None:
        missing = [key for key in MODEL_ENV_KEYS if not os.getenv(key)]
        if missing:
            raise HTTPException(
                status_code=500,
                detail=f"服务端缺少配置：{', '.join(missing)}，请检查 .env 后重启服务",
            )
        _model = ChatOpenAI(
            api_key=os.getenv("SILICONFLOW_API_KEY"),
            base_url=os.getenv("SILICONFLOW_BASE_URL"),
            model=os.getenv("SILICONFLOW_MODEL"),
        )
    return _model


@app.exception_handler(RequestValidationError)
async def on_request_validation_error(request: Request, exc: RequestValidationError):
    """把 Pydantic 的报错整理成 [{field, reason}]，比默认结构好读得多。"""
    details = []
    for err in exc.errors():
        # loc 形如 ("body", "history", 0, "role")，第一段 "body" 只是说"来自请求体"
        loc = err.get("loc", ())
        field = ".".join(str(item) for item in loc[1:]) or "body"
        details.append({"field": field, "reason": err.get("msg", "")})
    return JSONResponse(status_code=422, content={"detail": details})


@app.get("/health", summary="健康检查（无需鉴权）")
async def health():
    """探活接口，供部署脚本/负载均衡使用，故意不挂鉴权。"""
    return {"status": "ok"}


@app.post(
    "/chat",
    summary="流式对话接口",
    dependencies=[Depends(require_api_key)],
)
async def chat(payload: ChatRequest, model: ChatOpenAI = Depends(get_model)):
    # 1. 按轮数裁剪历史。history_len=0 表示一条历史都不带。
    keep = payload.history_len * 2
    history = payload.history[-keep:] if keep > 0 else []

    # 2. 组装消息列表
    #    history 里的 role 已经由 ChatMessage 限制成 user/assistant，
    #    不会有调用方伪造的 system 指令混进来。
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

    return StreamingResponse(
        generate_response(),
        media_type="text/plain; charset=utf-8",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=6066, log_level="info")
