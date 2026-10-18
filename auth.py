"""API Key 鉴权。

改造前 /chat 是完全开放的：谁拿到你的地址和端口，就能无限调用，
账单记在你头上。加鉴权只需要一个依赖函数，但要守住三条原则：

1. **失败时"关闭"而不是"开放"**。
   没配置 GATEWAY_API_KEY 时，拒绝所有请求（500），而不是默认放行。
   否则你哪天忘了配环境变量，服务就悄悄变成完全公开的了。

2. **用 secrets.compare_digest 比较，不要用 ==**。
   `a == b` 在第一个不同的字符处就返回，攻击者可以靠测量响应时间
   一个字符一个字符地把 key 猜出来（时序侧信道）。compare_digest 是常数时间。

3. **key 只从环境变量来**，代码里不出现明文，key 也不进 git。
"""

import os
import secrets

from dotenv import load_dotenv
from fastapi import Header, HTTPException, status

# 自己 load 一次，避免"auth 先于 load_dotenv 被 import"时读到空值。
# load_dotenv() 是幂等的，重复调用没有副作用。
load_dotenv()

# 在模块加载时读一次。改了 .env 要重启服务才生效。
API_KEY: str = os.getenv("GATEWAY_API_KEY", "")


def require_api_key(
    x_api_key: str | None = Header(
        default=None,
        alias="X-API-Key",
        description="调用方密钥，与服务端 .env 里的 GATEWAY_API_KEY 一致",
    ),
) -> None:
    """FastAPI 依赖：校验请求头里的 X-API-Key。

    只做校验，不返回值。用法是在路由上挂 `dependencies=[Depends(require_api_key)]`，
    校验不过会直接抛出 HTTPException，请求根本进不到业务函数。
    """
    # 情况一：服务端自己没配 key —— 这是配置事故，直接拒绝全部请求。
    if not API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="服务端未配置 GATEWAY_API_KEY，已拒绝所有请求（请检查 .env）",
        )

    # 情况二：没带 key，或带错了 —— 一律 401，且不告诉对方"是没带还是带错"。
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
