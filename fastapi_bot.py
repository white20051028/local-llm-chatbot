"""FastAPI 后端：流式对话接口。

本提交只做一件事：请求体改用 Pydantic 模型（schemas.py）校验，
非法请求在进入函数前就返回 422。

顺带修掉一个 bug：原来 history_len=0（滑块最左=不保留历史）时，
条件 `if history_len > 0 and ...` 不成立，反而把**全部**历史都带上了，
与界面上"0 = 不保留"的语义相反。
"""

import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_openai import ChatOpenAI

from schemas import ChatRequest

# 加载环境变量。必须在任何 os.getenv 之前执行。
load_dotenv()

app = FastAPI(
    title="本地对话机器人 API",
    description="流式对话接口。请求体由 Pydantic 模型校验。",
    docs_url="/docs",
    redoc_url="/redoc",
    swagger_js_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui-bundle.min.js",
    swagger_css_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui.min.css",
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 懒加载的模型客户端。
# 不放在模块顶层直接构造，有两个原因：
#   ① 没配 SILICONFLOW_API_KEY 时服务依然能启动（/health 可用、报错更清楚）；
#   ② 测试里可以把它换成假模型，不产生真实网络请求、不花钱。
_model: ChatOpenAI | None = None


def get_model() -> ChatOpenAI:
    """返回全局唯一的模型客户端（第一次调用时创建）。"""
    global _model
    if _model is None:
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


@app.get("/health", summary="健康检查")
async def health():
    """探活接口，供部署脚本/负载均衡使用。"""
    return {"status": "ok"}


@app.post("/chat", summary="流式对话接口")
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
