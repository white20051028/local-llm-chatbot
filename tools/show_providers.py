"""把 providers.toml 解析后的真实结构打印出来。

用法：
    python tools/show_providers.py

看代码看不懂的时候，先看数据长什么样——比读十遍代码有用。
"""

import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import providers  # noqa: E402

configs, default = providers.load_providers(ROOT / "providers.toml")

print("默认 provider:", default)
print()
print(f"一共有 {len(configs)} 个 provider：")
for name, cfg in configs.items():
    print(f"  {name}")
    for key, value in asdict(cfg).items():
        shown = value if value != "" else "（空，本地服务不需要密钥）"
        print(f"      {key:<12} = {shown}")
