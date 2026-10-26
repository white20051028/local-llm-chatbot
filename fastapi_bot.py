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
import asyncio
import logging
import openai
from providers import load_providers

# 挂到 uvicorn 的 logger 上，这样日志会出现在你启动服务的那个控制台里
logger = logging.getLogger("uvicorn.error")

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
# 启动时加载一次。配置有问题会在这里直接报错、服务起不来——这是对的，
# 总比运行到第一个请求时才炸好。
_PROVIDERS, DEFAULT_PROVIDER = load_providers(
    os.path.join(BASE_DIR, "providers.toml")
)

# 按 provider 名字缓存 client：每个后端只建一次（内部有连接池），之后复用。
_clients: dict[str, ChatOpenAI] = {}


def get_model(provider: str | None = None) -> ChatOpenAI:
    """按名字取模型客户端；不传就用默认 provider。"""
    name = provider or DEFAULT_PROVIDER

    cfg = _PROVIDERS.get(name)
    if cfg is None:
        # 客户端传了一个不存在的名字 —— 这是客户端的错，所以是 400 不是 500
        raise HTTPException(
            status_code=400,
            detail=f"未知的 provider：{name!r}；可用的有：{list(_PROVIDERS)}",
        )

    if name not in _clients:
        if cfg.api_key_env and not os.getenv(cfg.api_key_env):
            raise HTTPException(
                status_code=500,
                detail=f"provider '{cfg.name}' 需要环境变量 {cfg.api_key_env}，请检查 .env",
            )
        connect_timeout = float(os.getenv("LLM_CONNECT_TIMEOUT", "5"))
        read_timeout = float(os.getenv("LLM_READ_TIMEOUT", "15"))
        _clients[name] = ChatOpenAI(
            api_key=os.getenv(cfg.api_key_env) if cfg.api_key_env else "not-needed",
            base_url=cfg.base_url,
            model=cfg.model,
            request_timeout=(connect_timeout, read_timeout),
            max_retries=0,
        )

    return _clients[name]

# 这里加了个配置回显，以后一条名了就可以看出服务到底在和谁说话 curl.exe -s http://127.0.0.1:6066/health
@app.get("/health", summary="健康检查（无需鉴权）")
async def health():
    """探活接口。顺便回显当前生效的配置，避免"改了没生效"的排查成本。"""
    cfg = _PROVIDERS[DEFAULT_PROVIDER]
    return {
        "status": "ok",
        "provider": cfg.name,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "timeout": f"{os.getenv('LLM_CONNECT_TIMEOUT', '5')}/{os.getenv('LLM_READ_TIMEOUT', '15')}",
    }

def _is_retryable(exc: Exception) -> bool:
    """判断这个异常值不值得重试。

    判据不是"出错了"，而是"再试一次有可能成功"：
      - 网络层问题（连不上、超时）     → 值得
      - 429 限流                      → 值得（等一会儿再来）
      - 5xx                           → 值得（对方临时故障）
      - 400/401/403/404/422           → 不值得（我们的请求本身有问题，试一百次也一样）
    """
    # APITimeoutError 是 APIConnectionError 的子类，所以这一条同时覆盖"超时"和"连不上"
    if isinstance(exc, openai.APIConnectionError):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False

async def _open_stream(bound, messages):
    """打开上游流并返回 (stream, 第一个有内容的 chunk)。

    失败时先判断错误类型：可重试的按指数退避重试，不可重试的直接抛。
    """
    max_attempts = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
    last_error = None

    for attempt in range(1, max_attempts + 1):
        stream = bound.astream(messages)      # 每次重试都要新建一个流
        try:
            async for chunk in stream:
                if chunk.content:
                    return stream, chunk
        except Exception as e:
            if not _is_retryable(e) or attempt == max_attempts:
                raise
            last_error = e
            backoff = 2 ** (attempt - 1)      # 1s, 2s, 4s...
            logger.warning(
                "上游失败（第 %d/%d 次，%s），%d 秒后重试",
                attempt, max_attempts, type(e).__name__, backoff,
            )
            await asyncio.sleep(backoff)

    raise last_error if last_error else RuntimeError("上游没有返回任何内容")

@app.get(
    "/providers",
    summary="列出可用的模型后端",
    dependencies=[Depends(require_api_key)],
)
async def list_providers():
    """给前端用：告诉它有哪些后端可选、默认是哪个。

    故意不回传 base_url 和 api_key_env：
    前者可能是内网地址，后者是内部实现细节。
    """
    return {
        "default": DEFAULT_PROVIDER,
        "providers": [
            {"name": cfg.name, "model": cfg.model}
            for cfg in _PROVIDERS.values()
        ],
    }
@app.post("/chat", summary="流式对话接口", dependencies=[Depends(require_api_key)])
async def chat(payload: ChatRequest):
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

    # 3. 取本次请求要用的后端（不传就用默认）
    model = get_model(payload.provider)

    # 4. 绑定本次请求的采样参数
    bound = model.bind(
        temperature=payload.temperature,
        top_p=payload.top_p,
        max_tokens=payload.max_tokens,
    )

    # 5. 先连上游、拿到第一个 chunk。
    #    关键：失败必须发生在这里（还没返回响应），而不是在流开始之后。

    try:
        stream, first_chunk = await _open_stream(bound, messages)
    except Exception as e:
        logger.exception("调用上游失败")   # ← 加这行
        raise HTTPException(status_code=502, detail=f"上游模型服务不可用：{type(e).__name__}")

    async def generate_response():
        yield first_chunk.content
        async for chunk in stream:
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
