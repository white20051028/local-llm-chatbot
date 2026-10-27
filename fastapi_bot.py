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
from providers import BackendState, build_chain, load_providers
from probe import probe_all
import time

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


# 启动时加载一次。配置有问题会在这里直接报错、服务起不来——这是对的，
# 总比运行到第一个请求时才炸好。
_PROVIDERS, DEFAULT_PROVIDER, PRIORITY = load_providers(
    os.path.join(BASE_DIR, "providers.toml")
)

# 探测结果和降级链，由 _init_backends() 在下面填充
_STATES: dict[str, BackendState] = {}
_CHAIN: list[str] = [DEFAULT_PROVIDER]

# 按 provider 名字缓存 client：每个后端只建一次（内部有连接池），之后复用。
_clients: dict[str, ChatOpenAI] = {}

def _init_backends() -> None:
    """启动时探测每个后端，生成降级链。

    探测失败的后端不踢掉，只排到链尾并标"未验证"——
    网络抖一下也会探测失败，不能因此误杀一个能用的后端。
    """
    global _CHAIN, _STATES

    # 测试里会把这个设成 false：否则每个测试都会真的发一次网络请求
    if os.getenv("PROBE_ON_STARTUP", "true").lower() != "true":
        _CHAIN = [DEFAULT_PROVIDER, *[n for n in PRIORITY if n != DEFAULT_PROVIDER]]
        logger.info("跳过探测（PROBE_ON_STARTUP=false）；降级链：%s", " → ".join(_CHAIN))
        return

    logger.info("探测模型后端可用性……")
    _STATES = probe_all(_PROVIDERS)

    for name, state in _STATES.items():
        if state.verified:
            logger.info(
                "  [可用]   %-14s %5dms  %s", name, state.latency_ms, _PROVIDERS[name].model
            )
        else:
            logger.info("  [不可用] %-14s    ——    %s", name, state.reason)

    _CHAIN = build_chain(_PROVIDERS, DEFAULT_PROVIDER, PRIORITY, _STATES)

    if len(_CHAIN) == 1:
        logger.info("已加载 1 个后端，无降级链（请求路径零额外开销）")
        return

    parts = [
        name if _STATES.get(name) and _STATES[name].verified else f"{name}(未验证)"
        for name in _CHAIN
    ]
    logger.info("降级链：%s", " → ".join(parts))


_init_backends()

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
    """探活接口。回显当前生效的后端与模型，避免"改了没生效"的排查成本。

    故意不回显 base_url：这个接口**免鉴权**，而 base_url 可能指向内网地址
    （本地 Ollama 是 127.0.0.1，公司内网可能是 10.x），等于对外泄露拓扑。
    需要看 base_url 时去启动日志或需要鉴权的 /providers 拿。
    """
    cfg = _PROVIDERS[DEFAULT_PROVIDER]
    return {
        "status": "ok",
        "provider": cfg.name,
        "model": cfg.model,
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

def _should_fallback(exc: Exception) -> bool:
    """这个错误值不值得换一个后端再试。

    和 _is_retryable 的区别：那个问"同一个后端要不要再试一次"，
    这个问"要不要换一个后端"。

    该降级：超时 / 连不上 / 5xx / 401 403（key 错、欠费）/ 我们自己抛的 500（缺 key）
    不该降级：400 422（请求本身不合法，换谁都一样错）
    """
    if isinstance(exc, HTTPException):
        return exc.status_code >= 500
    if isinstance(exc, openai.BadRequestError):
        return False
    if isinstance(exc, openai.UnprocessableEntityError):
        return False
    return True

async def _open_stream(bound, messages, deadline: float | None = None):
    """打开上游流并返回 (stream, 第一个有内容的 chunk)。

    deadline 是整条降级链的截止时刻（time.monotonic() 的时间点）。
    剩余时间不够就不再重试，把错误抛给上层去决定要不要换后端。
    """
    max_attempts = int(os.getenv("LLM_MAX_ATTEMPTS", "3"))
    last_error = None

    for attempt in range(1, max_attempts + 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise last_error if last_error else TimeoutError("总预算已用完")

        stream = bound.astream(messages)
        try:
            async for chunk in stream:
                if chunk.content:
                    return stream, chunk
        except Exception as e:
            if not _is_retryable(e) or attempt == max_attempts:
                raise
            last_error = e
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "上游失败（第 %d/%d 次，%s），%d 秒后重试",
                attempt, max_attempts, type(e).__name__, backoff,
            )
            await asyncio.sleep(backoff)

    raise last_error if last_error else RuntimeError("上游没有返回任何内容")

async def _open_stream_with_fallback(chain, messages, *, temperature, top_p, max_tokens):
    """按 chain 顺序逐个尝试后端，返回 (实际用的名字, stream, first_chunk)。

    两层重试的分工：
      _open_stream                → 同一个后端内部重试 N 次
      _open_stream_with_fallback  → 这个后端彻底不行了，换下一个
    """
    # 只有一个后端时完全没有降级可言：直接走原路径，零额外开销
    if len(chain) <= 1:
        name = chain[0]
        model = get_model(name)
        bound = model.bind(temperature=temperature, top_p=top_p, max_tokens=max_tokens)
        stream, first_chunk = await _open_stream(bound, messages)
        return name, stream, first_chunk
    
    budget = float(os.getenv("LLM_FALLBACK_BUDGET", "50"))
    deadline = time.monotonic() + budget
    last_error: Exception | None = None

    for index, name in enumerate(chain):
        if time.monotonic() >= deadline:
            logger.warning("总预算 %.0f 秒用完，放弃剩余 %d 个后端", budget, len(chain) - index)
            break

        if index > 0:
            logger.warning("降级：切换到第 %d 顺位的 %s", index + 1, name)

        try:
            model = get_model(name)
            bound = model.bind(temperature=temperature, top_p=top_p, max_tokens=max_tokens)
            stream, first_chunk = await _open_stream(bound, messages, deadline=deadline)
        except Exception as e:
            if not _should_fallback(e):
                raise
            last_error = e
            logger.warning("provider %s 失败（%s），准备降级", name, type(e).__name__)
            continue

        if index > 0:
            logger.warning("降级成功：本次实际由 %s 提供服务", name)
        return name, stream, first_chunk

    raise last_error if last_error else RuntimeError("所有后端都不可用")

@app.get(
    "/providers",
    summary="列出可用的模型后端",
    dependencies=[Depends(require_api_key)],
)
async def list_providers():
    """给前端用：可选后端、当前降级链、每个后端是否验证过。

    故意不回传 base_url 和 api_key_env：
    前者可能是内网地址，后者是内部实现细节。
    """
    return {
        "default": DEFAULT_PROVIDER,
        "chain": _CHAIN,
        "providers": [
            {
                "name": cfg.name,
                "model": cfg.model,
                "verified": bool(_STATES[cfg.name].verified) if cfg.name in _STATES else False,
                "latency_ms": _STATES[cfg.name].latency_ms if cfg.name in _STATES else None,
                "reason": _STATES[cfg.name].reason if cfg.name in _STATES else "未探测",
            }
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

    # 3. 决定这次用哪些后端
    #    显式指定了 provider 就只用它：用户说"我要 ollama"，就不该偷偷换成别的
    if payload.provider:
        chain = [payload.provider]
        if payload.provider not in _PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"未知的 provider：{payload.provider!r}；"
                       f"可用的有：{list(_PROVIDERS)}",
            )
    else:
        chain = _CHAIN or [DEFAULT_PROVIDER]
    provider_name = chain[0]

    # 4-5. 按链依次尝试：每个后端内部会重试，彻底不行才换下一个
    try:
        used_name, stream, first_chunk = await _open_stream_with_fallback(
            chain,
            messages,
            temperature=payload.temperature,
            top_p=payload.top_p,
            max_tokens=payload.max_tokens,
        )
    except Exception as e:
        logger.exception("所有后端都失败")
        raise HTTPException(
            status_code=502,
            detail=f"上游模型服务不可用：{type(e).__name__}",
        )

    cfg = _PROVIDERS[used_name]
    headers = {"X-Provider": cfg.name, "X-Model": cfg.model}
    if used_name != provider_name:
        headers["X-Fallback-From"] = provider_name      # 告诉调用方发生了降级

    async def generate_response():
        yield first_chunk.content
        async for chunk in stream:
            if chunk.content:
                yield chunk.content

    # charset 要显式写：只写 text/plain 时，某些客户端会按 latin-1 解码，中文变乱码。
    # X-Provider / X-Model 让调用方一眼看出这次是谁服务的——
    # 排查"到底切没切成功"全靠它，否则只能靠猜。
    return StreamingResponse(
        generate_response(),
        media_type="text/plain; charset=utf-8",
        headers=headers
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=6066, log_level="info")
