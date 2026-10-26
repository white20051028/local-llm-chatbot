"""providers.py 的自检脚本。

用法（在项目根目录）：
    python tools/check_providers.py

它会检查你的加载器是否满足这四条约定：
    1. 能读出 providers.toml 里的全部 provider
    2. 能读出 default
    3. default 指向一个不存在的名字时，要抛 ValueError（而不是静默用一个错的）
    4. 缺 base_url / model 时，也要抛 ValueError

先跑一遍——现在 providers.py 还没写，会报 ModuleNotFoundError，那是正常的。
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from providers import load_providers
except ImportError as e:
    print(f"❌ 还导入不了 providers.py：{e}")
    print("   下一步：在项目根目录新建 providers.py，实现 load_providers()")
    sys.exit(1)

failed = 0


def check(label, fn):
    global failed
    try:
        fn()
        print(f"  PASS  {label}")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {label}")
        print(f"        {type(e).__name__}: {e}")
        failed += 1


def case_normal():
    providers, default = load_providers(ROOT / "providers.toml")

    assert isinstance(providers, dict), "第一个返回值应该是 dict"
    assert "siliconflow" in providers, "应该有 siliconflow"
    assert "ollama" in providers, "应该有 ollama"
    assert default == "siliconflow", f"default 应该是 siliconflow，实际是 {default!r}"

    cfg = providers["siliconflow"]
    # 允许 dataclass / 普通对象 / dict 三种写法，方便你自由实现
    get = (lambda k: getattr(cfg, k)) if not isinstance(cfg, dict) else (lambda k: cfg[k])
    assert get("base_url").startswith("https://"), "base_url 没读对"
    assert get("model"), "model 是空的"
    assert get("api_key_env") == "SILICONFLOW_API_KEY", "api_key_env 没读对"

    ollama = providers["ollama"]
    get2 = (lambda k: getattr(ollama, k)) if not isinstance(ollama, dict) else (lambda k: ollama[k])
    assert get2("api_key_env") == "", "ollama 的 api_key_env 应该是空字符串"


def _load_text(text):
    with tempfile.NamedTemporaryFile(
        "w", suffix=".toml", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        path = f.name
    try:
        return load_providers(Path(path))
    finally:
        Path(path).unlink(missing_ok=True)


def case_bad_default():
    text = """
default = "not-exist"

[providers.a]
base_url = "http://x/v1"
model = "m"
api_key_env = ""
"""
    try:
        _load_text(text)
    except ValueError as e:
        assert "not-exist" in str(e), f"报错信息里应该提到那个名字，实际是：{e}"
        return
    raise AssertionError("default 指向不存在的 provider，却没有抛 ValueError")


def case_missing_field():
    text = """
default = "a"

[providers.a]
model = "m"
api_key_env = ""
"""
    try:
        _load_text(text)
    except ValueError:
        return
    raise AssertionError("缺 base_url 却没有抛 ValueError")


print("检查 providers.py：")
check("正常加载 providers.toml", case_normal)
check("default 指向不存在的名字 -> ValueError", case_bad_default)
check("provider 缺字段 -> ValueError", case_missing_field)

print()
if failed:
    print(f"❌ 有 {failed} 项没过")
    sys.exit(1)
print("✅ 全部通过，可以去改 fastapi_bot.py 了")
