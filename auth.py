"""API Key 鉴权：校验请求头里的 X-API-Key。

三条设计原则：
1. 失败时"关闭"而不是"开放"（fail closed）；
2. 用 secrets.compare_digest 做常数时间比较，防时序侧信道；
3. key 只从环境变量来，代码里永不出现明文。
"""

import os
import secrets

from dotenv import load_dotenv
from fastapi import Header, HTTPException, status

# 自己 load 一次：避免 auth 先于 load_dotenv 被 import 时读到空值。
# load_dotenv() 是幂等的，重复调用没有副作用。
load_dotenv()

# 模块加载时读一次。改了 .env 必须重启进程才生效
# （uvicorn 的 --reload 只监听 .py，不监听 .env）。
API_KEY: str = os.getenv("GATEWAY_API_KEY", "")


def require_api_key(
    x_api_key: str | None = Header(
        default=None,
        # 显式指定头名，别让 FastAPI 去猜下划线怎么转成连字符。
        # HTTP 头本身大小写不敏感，但文档上显示成 X-API-Key 才规范。
        alias="X-API-Key",
        description="调用方密钥，与服务端 .env 里的 GATEWAY_API_KEY 一致",
    ),
) -> None:
    """FastAPI 依赖：校验请求头。只做检查，不返回值。

    挂在路由上的写法：
        @app.post("/chat", dependencies=[Depends(require_api_key)])

    因为它是在"进入路由函数之前"执行的，一旦这里抛异常，请求立刻中止，
    请求体校验根本不会被执行 —— 这就是"key 错看到 401、key 对才看到 422"的原因。
    """

    # ① 服务端自己没配 key —— 这是配置事故，拒绝一切请求。
    #    注意不能"没配就放行"：那样你哪天忘了加环境变量，
    #    服务会静默变成完全公开的，而且没有任何报错，你根本不会发现。
    if not API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务端未配置 GATEWAY_API_KEY，已拒绝所有请求（请检查 .env）",
        )

    # ② 没带 key，或带错了 —— 一律 401。
    #    故意不区分"没带"和"带错"，不给攻击者额外信息。
    #    用 compare_digest 而不是 ==：== 比到第一个不同的字符就返回，
    #    攻击者能靠测响应时间一个字符一个字符地猜（timing side-channel）。
        # Header 是客户端可控的，可能带非 ASCII 字符（比如中文），
    # 而 compare_digest 不接受非 ASCII 的 str —— 先转成 bytes 再比。
    if not x_api_key or not secrets.compare_digest(
        x_api_key.encode("utf-8"), API_KEY.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
