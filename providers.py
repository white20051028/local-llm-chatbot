"""读取 providers.toml，返回可用的模型后端列表。

这是一个"模块"，不是"脚本"：被 import 时只定义函数和类型，
不做任何 IO、不打印、不 input()。

代码分五段，每段只干一件事。建议按这个顺序读：
    ① load_providers  ← 先读它（像目录）
    ② read_toml       ← 需要时再看
    ③ build_providers
    ④ check_default / check_priority
    ⑤ build_chain     ← 降级链怎么排出来的
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
    context_window: int = 8192      # 没填时的保守默认

@dataclass(frozen=True)
class BackendState:
    """一次探测的结果。"""

    verified: bool
    latency_ms: int = 0
    reason: str = ""


# ============================================================
# ① 目录：把三步串起来
# ============================================================
def load_providers(
    path: Path,
) -> tuple[dict[str, ProviderConfig], str, list[str]]:
    """读取并校验 providers.toml，返回 ({名字: 配置}, 默认名字, 用户偏好的顺序)。"""
    data = read_toml(path)
    providers = build_providers(data)
    default = check_default(data.get("default"), providers)
    priority = check_priority(data.get("priority"), providers)
    return providers, default, priority


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
            context_window=int(item.get("context_window", 8192)),
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

def check_priority(priority, providers: dict[str, ProviderConfig]) -> list[str]:
    """校验用户写的 priority（想要的降级顺序），返回清洗后的列表。

    priority 是可选的：
      没写 / 空 → 返回 []，链完全按探测延迟排
      写了     → 必须是数组，且每个名字都得真实存在
    """
    if not priority:
        return []
    if not isinstance(priority, list):
        raise ValueError('priority 必须是数组，例如 priority = ["ollama"]')

    unknown = [name for name in priority if name not in providers]
    if unknown:
        raise ValueError(
            f"priority 里有不存在的后端：{unknown}；可用的有：{list(providers)}"
        )
    return list(priority)


def build_chain(
    providers: dict[str, ProviderConfig],
    default: str,
    priority: list[str],
    states: dict[str, BackendState],
) -> list[str]:
    """生成降级链。

    规则，按优先级从高到低：
      1. default 永远第一位
      2. priority 里用户点名的 —— 用户的显式意愿压过一切
      3. 其余探测通过的，按 providers.toml 里的段顺序
      4. 探测没通过的，排最后（不踢掉：探测可能误判）

    为什么第 3 条按段顺序而不是按延迟：
      本地 0.5B 一定比云端大模型快，因为它就在本机、没有网络往返。
      按延迟排会让"最快但最弱"的模型排到前面，正好和用户想要的相反。
      延迟只用来显示（/providers 里的 latency_ms），不用来排序。
    """
    chain = [default]

    for name in priority:
        if name not in chain:
            chain.append(name)

    # 遍历 providers 而不是 states：providers 保持 toml 里的段顺序，states 不保证
    verified = [
        name
        for name in providers
        if name not in chain and states.get(name) and states[name].verified
    ]
    chain.extend(verified)

    chain.extend(name for name in providers if name not in chain)
    return chain