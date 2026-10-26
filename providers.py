"""读取 providers.toml，返回可用的模型后端列表。

这是一个"模块"，不是"脚本"：被 import 时只定义函数和类型，
不做任何 IO、不打印、不 input()。

代码分四段，每段只干一件事。建议按这个顺序读：
    ① load_providers  ← 先读它（4 行，像目录）
    ② read_toml       ← 需要时再看
    ③ build_providers
    ④ check_default
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderConfig:
    """一个模型后端的配置。frozen=True 表示创建后不可修改。

    注意：这里没有 api_key 字段，只有 api_key_env（密钥所在的变量名）。
    密钥本身永远从环境变量读，不进代码、不进 toml。
    """

    name: str
    base_url: str
    model: str
    api_key_env: str


# ============================================================
# ① 目录：把三步串起来
# ============================================================
def load_providers(path: Path) -> tuple[dict[str, ProviderConfig], str]:
    """读取并校验 providers.toml，返回 ({名字: 配置}, 默认名字)。

    只负责"按顺序调用三步"，不干具体活。所以这四行就是整个流程。
    """
    data = read_toml(path)                       # 第 1 步：拿到原始 dict
    providers = build_providers(data)            # 第 2 步：dict → ProviderConfig
    default = check_default(data.get("default"), providers)   # 第 3 步：确认默认项合法
    return providers, default


# ============================================================
# ② 读文件：只负责"打开并解析"，不判断内容对不对
# ============================================================
def read_toml(path: Path) -> dict:
    """把 toml 文件读成一个普通 dict。"""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"找不到配置文件：{path}")

    # tomllib 必须用二进制模式打开。用 "r" 会报 TypeError 或编码错误。
    with open(path, "rb") as f:
        return tomllib.load(f)


# ============================================================
# ③ 转换：把 [providers.xxx] 那层 dict 翻译成对象
# ============================================================
def build_providers(data: dict) -> dict[str, ProviderConfig]:
    """输入形如 {"providers": {"ollama": {"base_url": ...}}}，输出 {名字: 对象}。"""
    raw = data.get("providers")

    # 文件里可能压根没写 [providers.xxx] 段
    if not isinstance(raw, dict) or not raw:
        raise ValueError("providers.toml 里没有任何 [providers.xxx] 配置段")

    providers: dict[str, ProviderConfig] = {}

    # 逐个后端翻译。name 是键名（如 "ollama"），item 是它下面那个小 dict。
    for name, item in raw.items():
        # base_url 和 model 是必填；缺一个就没法用
        for key in ("base_url", "model"):
            if not item.get(key):
                raise ValueError(f"provider '{name}' 缺少 {key}")

        providers[name] = ProviderConfig(
            name=name,
            base_url=item["base_url"],
            model=item["model"],
            # api_key_env 可以省略：本地 Ollama 不需要密钥
            api_key_env=item.get("api_key_env", ""),
        )

    return providers


# ============================================================
# ④ 校验：default 必须指向一个真实存在的后端
# ============================================================
def check_default(default: str | None, providers: dict[str, ProviderConfig]) -> str:
    """确认 default 合法，并原样返回它。"""
    if not default:
        raise ValueError("providers.toml 缺少 default（默认用哪个 provider）")

    if default not in providers:
        raise ValueError(
            f"default 指向不存在的 provider：{default!r}；可用的有：{list(providers)}"
        )

    return default
