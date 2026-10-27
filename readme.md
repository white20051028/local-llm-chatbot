# 本地调用api大模型多轮对话机器人

> 一个前后端分离的流式对话 Web 应用：FastAPI 后端对接 OpenAI 兼容的大模型 API（硅基流动 / Ollama / vLLM 均可），Gradio 前端提供聊天交互与参数调节面板。

## ✨ 功能特性

- **流式逐字输出**：基于 LangChain 原生 `astream()`，打字机效果实时渲染
- **多轮上下文记忆**：可调节保留的历史对话轮数，自动裁剪超长上下文
- **参数可视化调节**：温度、top_p、max_tokens、系统提示词全部支持滑块实时调整
- **前后端分离**：FastAPI 提供流式接口，Gradio 作为前端，可独立替换/扩展
- **接口鉴权**：`/chat` 必须携带 `X-API-Key` 请求头，未配置密钥时拒绝全部请求（fail closed）
- **请求体校验**：Pydantic 模型定义全部字段与上下界，非法请求返回 422 并指出具体字段
- **消息正文双格式兼容**：`content` 既可以是字符串，也可以是 `[{"type": "text", "text": "..."}]` 内容块数组——后者是 Gradio 6 的默认形态，也是 OpenAI chat API 支持的写法
- **配置与代码分离**：API Key、模型、地址全部通过 `.env` 管理，代码零敏感信息
- **自动化测试**：pytest 覆盖鉴权、校验、历史裁剪共 18 个用例，不联网、不花钱
- **CORS 跨域支持**：前后端分离部署无跨域问题

## 🛠 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn |
| 数据校验 | Pydantic v2 |
| 大模型调用 | LangChain / langchain-openai（兼容 OpenAI 协议） |
| 前端界面 | Gradio |
| 环境管理 | python-dotenv |
| 测试 | pytest + httpx（TestClient） |
| 模型接入 | 任意 OpenAI 兼容接口（硅基流动、Ollama、vLLM、OpenAI 等） |

## 🏗 请求链路

```
用户(Gradio 前端 :7860)
   │  POST /chat  Header: X-API-Key
   │  Body: query + history + 参数
   ▼
FastAPI 后端 (:6066)
   │  1. 依赖 require_api_key 校验密钥 → 失败直接 401，不进业务函数
   │  2. Pydantic 校验请求体 → 失败直接 422，不进业务函数
   │  3. 按 history_len 裁剪历史
   │  4. 组装 system + history + user 消息
   │  5. ChatOpenAI.bind(参数).astream(messages)
   ▼
大模型 API（硅基流动 / Ollama / vLLM）
   │  SSE 流式返回 token
   ▼
StreamingResponse → 前端逐字渲染
```

## 🚀 快速开始

### 环境要求
- Python 3.10 及以上
- 一个 OpenAI 兼容服务的 API Key（本项目默认使用硅基流动的 Qwen2.5-7B-Instruct）

### 1. 克隆仓库并安装依赖
```bash
git clone <你的仓库地址>
cd <项目目录>

# 建议使用虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt

# 想跑测试的话，再装开发依赖
pip install -r requirements-dev.txt
```

### 2. 配置环境变量
复制 `.env.example` 为 `.env`，填入你自己的配置：
```bash
# Windows
copy .env.example .env
# macOS/Linux
# cp .env.example .env
```
编辑 `.env`：
```env
SILICONFLOW_API_KEY=sk-你的真实密钥
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_MODEL=Qwen/Qwen2.5-7B-Instruct

# 本服务自己的调用密钥，随便生成一串足够长的随机字符
GATEWAY_API_KEY=你自己生成的一串随机值
```

生成 `GATEWAY_API_KEY` 的推荐做法：
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> ⚠️ `.env` 已加入 `.gitignore`，**切勿提交到 Git 仓库**，否则 API Key 会泄露。

### 3. 启动后端
```bash
python fastapi_bot.py
# 看到 Uvicorn running on http://0.0.0.0:6066 即启动成功
```

### 4. 启动前端
新开一个终端：
```bash
python gradio_ui.py
```
浏览器打开 **http://127.0.0.1:7860** 即可开始对话。

后端接口文档（可直接调试）：http://127.0.0.1:6066/docs

## 🔐 接口鉴权

`/chat` 现在需要鉴权，`/health` 不需要（留给部署探活用）。

```bash
curl http://127.0.0.1:6066/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: 你在 .env 里配的值" \
  -d '{"query": "你好"}'
```

在 `/docs` 里调试时，先点右上角 **Authorize** 填入密钥，或者直接在 `X-API-Key` 输入框里填。

| 情况 | 返回 |
|---|---|
| 没带 `X-API-Key` 或值不对 | `401 {"detail": "无效的 API Key"}` |
| 服务端自己没配 `GATEWAY_API_KEY` | `500`，并提示检查 `.env` |

设计上做了两件事，值得留意：
1. **fail closed**：服务端没配密钥时拒绝所有请求，而不是默认放行。否则哪天忘了配环境变量，服务就悄悄变成完全公开。
2. **常数时间比较**：用 `secrets.compare_digest` 而不是 `==`，避免通过响应时间猜密钥（时序侧信道）。

## 🧪 运行测试

```bash
python -m pytest -q
```

测试不联网、不需要真实 API Key：模型用 `app.dependency_overrides` 换成了假对象。

覆盖范围：
- 鉴权：无 key / 错误 key → 401；服务端未配置 key → 500；`/health` 免鉴权
- 校验：缺 `query`、`role` 非法、history 里塞 `system`、参数越界、多传未知字段 → 422
- 业务：流式内容拼接正确、采样参数透传、`history_len` 裁剪语义
- 韧性：上游超时重试 3 次后返回 502；400 类错误**不重试**（只调用 1 次）

## 🛡 故障与降级

上游是别人的服务，它会挂。这里的三个机制保证**挂的时候客户端能知道**：

| 机制 | 行为 | 失败时 |
|---|---|---|
| **超时** | connect 5s / read 15s，可配 | 15 秒内失败，不会无限挂起 |
| **重试** | 只重试可恢复的错误，最多 3 次，退避 1s / 2s | 最差约 48 秒后失败 |
| **首 token 前置** | 先取到第一个 chunk 才返回流 | 上游不可用 → **502**，而不是 `200` + 空内容 |

### 哪些错误会重试

| 情况 | 重试 | 理由 |
|---|---|---|
| 连不上 / 超时（`APIConnectionError`） | ✅ | 网络抖动，第二次可能就好 |
| 429 限流 | ✅ | 等一会儿再来 |
| 5xx（`InternalServerError`） | ✅ | 对方临时故障 |
| 400 / 401 / 403 / 404 / 422 | ❌ | 请求本身有问题，重试一百次也一样 |

> 判断依据是 `status_code`，不是异常类名。`_is_retryable()` 只认这两件事：
> 是不是 `APIConnectionError`（含超时），以及 `status_code` 是不是 429/5xx。

### 为什么"首 token 前置"值得单独做

`StreamingResponse` 一旦开始 yield，HTTP 状态行就已经发出去了。上游如果在这之后才报错，
客户端收到的是 `200 OK` + 半句话 —— **看起来像正常说完了，监控和日志都发现不了**。

把"连上游 + 取第一个 chunk"挪到 `return` 之前，这类失败才能变成真正的 `502`。

> **已知限制**：第 2 个 chunk 之后断流仍然会静默结束（HTTP 无法反悔）。
> 彻底修需要换 SSE 协议发 `event: error`，属于后续工作。

### 已知取舍：最差等待约 48 秒

3 次 × 15 秒 + 退避 ≈ 48 秒。这是「尽量救回来」和「别让用户等太久」之间的权衡。

想缩短就改配置，不用动代码：

```env
LLM_READ_TIMEOUT=10      # 最差降到 ~33 秒
LLM_MAX_ATTEMPTS=2       # 最差降到 ~20 秒
```

### 怎么自己验证

```bash
python tools/measure_retry.py            # 一条命令，自带假上游
```

输出会打印**实际尝试次数**、**总耗时**，以及理论值。两者差得多就说明配置或代码有问题。

### 演练记录（真实运行输出）

**① 正常情况**

```console
$ curl.exe -s http://127.0.0.1:6066/health
{"status":"ok","model":"Qwen/Qwen2.5-7B-Instruct","base_url":"https://api.siliconflow.cn/v1","timeout":"5/15"}

$ python tools/probe_failure.py
目标: http://127.0.0.1:6066/chat
  HTTP 状态 : 200
  耗时      : 1.63 秒
  响应内容  : '你好！很高兴为你提供帮助。有什么问题或需要咨询的内容吗？'
```

**② 上游挂掉**（把 `base_url` 指向一个只接受连接、永不响应的假上游）

```console
$ python tools/probe_failure.py
目标: http://127.0.0.1:6066/chat
  HTTP 状态 : 502  ← 客户端拿到了明确错误
  耗时      : 48.23 秒
  响应内容  : '{"detail":"上游模型服务不可用：OpenAITimeoutError"}'
```

服务端日志（每次重试都留痕）：

```console
WARNING:  上游失败（第 1/3 次，OpenAITimeoutError），1 秒后重试
WARNING:  上游失败（第 2/3 次，OpenAITimeoutError），2 秒后重试
ERROR:    调用上游失败
Traceback (most recent call last):
  ...
openai.APITimeoutError: Request timed out.
INFO:     127.0.0.1:56331 - "POST /chat HTTP/1.1" 502 Bad Gateway
```

**③ 恢复**（改回真实地址）

```console
$ python tools/probe_failure.py
  HTTP 状态 : 200
  耗时      : 1.58 秒
  响应内容  : '你好！有什么我可以帮你的吗？'
```

### 演练记录（5 张实际运行截图）

完整过程见 [docs/上游故障可见化演练.docx](docs/上游故障可见化演练.docx)：正常 → 制造故障 → 502 → 恢复，每一步都有截图和说明。

> 三个数字对照着看：**改前是 `200` + 空内容 + 无限等待；改后是 `502` + 明确原因 + 48 秒封顶；
> 而恢复之后，流式体验没有任何变化。**

## 📂 项目结构

```
.
├── fastapi_bot.py        # 后端：路由、模型客户端、异常处理
├── schemas.py            # 请求体模型（Pydantic），负责字段与上下界校验
├── auth.py               # API Key 鉴权依赖
├── providers.toml        # 模型后端注册表（结构在此，密钥在 .env）
├── providers.py          # 读取并校验 providers.toml，生成降级链
├── probe.py              # 启动时探测每个后端能不能出字（max_tokens=1）
├── gradio_ui.py          # 前端：Gradio 聊天界面与参数面板
├── tests/
│   └── test_api.py       # 接口测试（pytest，34 条）
├── tools/                # 手工排错与验证脚本（不参与自动测试）
│   ├── smoke.py                # 校验层冒烟测试
│   ├── smoke_auth.py           # 鉴权层冒烟测试
│   ├── check_schema.py         # schema 约束自检
│   ├── check_providers.py      # providers 加载器自检
│   ├── show_providers.py       # 打印解析后的后端配置
│   ├── probe_failure.py        # 打一次 /chat，打印状态码/耗时/响应体
│   ├── silent_upstream.py      # 假上游：接受连接但永不响应
│   ├── measure_model_timeout.py # 测模型层多久放弃
│   └── measure_retry.py        # 一条命令测重试次数与总耗时
├── docs/
│   ├── TROUBLESHOOTING.md   # 踩坑记录：七个真实故障的现象/根因/修法
│   └── 优化与学习流程.md      # 从 demo 到可用服务的完整改造过程
├── static/               # 本地化的 swagger-ui 资源（/docs 不依赖 CDN）
│   ├── swagger-ui-bundle.js
│   └── swagger-ui.css
├── pytest.ini            # pytest 配置
├── requirements.txt      # 运行时依赖
├── requirements-dev.txt  # 开发/测试依赖
├── .env.example          # 环境变量模板
├── .env                  # 本地配置（不提交 Git）
├── .gitattributes        # 统一换行符；static/ 不做转换
└── .gitignore
```

> 这个项目从 demo 改成可用服务的过程中踩了七个坑（配置缺失被报成 500、文档示例自己不合法、Gradio 第二轮必 422、`/docs` 一片白……），
> 每个坑的现象、排查过程、根因和修法都记在 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) 里。
>
> `/docs` 的静态资源放在 `static/`，**不依赖任何 CDN**，断网也能打开接口文档。

## ⚙️ 多后端：加一个、切一个

后端列表在 **`providers.toml`**，不在 `.env` 里。密钥仍然在 `.env`（文件里只存变量名）。

```toml
default = "siliconflow"

[providers.siliconflow]
base_url = "https://api.siliconflow.cn/v1"
model = "Qwen/Qwen2.5-7B-Instruct"
api_key_env = "SILICONFLOW_API_KEY"     # 密钥所在的 .env 变量名

[providers.ollama]
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5:0.5b"
api_key_env = ""                         # 本地服务不校验 key
```

**加一个新后端** = 加一段 `[providers.xxx]` + 在 `.env` 里补对应的 key，重启即可。

> ⚠️ **改完 `providers.toml` 必须手动重启服务。** uvicorn 的 `--reload` 只监听 `.py`，
> 不监听 `.toml`——你以为新配置生效了，其实服务内存里还是旧表，现象是"新加的后端在
> `/providers` 里查不到"。
> 重启后启动日志会打印 `已加载 N 个模型后端：...`，用它确认新后端真的进来了。

**切一个** 有两种方式：

```bash
# ① 改默认值：改 providers.toml 里的 default，重启
# ② 单次请求指定（不改默认）：
curl -X POST http://127.0.0.1:6066/chat \
  -H "X-API-Key: $GATEWAY_API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "你好", "provider": "ollama"}'
```

看看有哪些可用：

```bash
curl http://127.0.0.1:6066/providers -H "X-API-Key: $GATEWAY_API_KEY"
```

### 为什么不支持"客户端自己传 base_url"

一个看起来更灵活的设计是让请求带上任意地址。**那是一个 SSRF 漏洞**：客户端可以让你的服务器去访问任意内网地址（例如云厂商元数据 `169.254.169.254`）。

所以这里只接受 **provider 名字**，真实 URL 由服务端配置决定。想接一个新后端，正确做法是让管理员改 `providers.toml`，而不是让终端用户传 URL。

### 每次响应都标明是谁服务的

响应头里带 `X-Provider` 和 `X-Model`，不用猜"到底切没切成功"：

```bash
curl -i -s -X POST http://127.0.0.1:6066/chat \
  -H "X-API-Key: $GATEWAY_API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "你好", "provider": "ollama"}' | head -5

# HTTP/1.1 200 OK
# x-provider: ollama
# x-model: qwen2.5:0.5b
```

### 实测记录

两个后端都真实跑通过（不是假模型）：

| 请求 | X-Provider | X-Model | 耗时 | 返回内容 |
|---|---|---|---|---|
| 不传 `provider` | `siliconflow` | `Qwen/Qwen2.5-7B-Instruct` | 3.69s | "我是一个来自阿里云的语言模型，名叫通义千问…" |
| `provider: "ollama"` | `ollama` | `qwen2.5:0.5b` | 4.08s | "我是一个AI助手，可以回答各种问题。" |
| `provider: "不存在的"` | — | — | — | `400 未知的 provider：'不存在的'；可用的有：['siliconflow', 'ollama']` |

第一行来自云端 7B，第二行来自本机 0.5B——**两条完全不同的链路，同一个接口**。

## 🔀 自动降级

主后端挂了，自动换下一个能用的——不用重启，不用人工介入。

### 怎么工作

**启动时探测**每个后端：发一次 `max_tokens=1` 的 chat，看它能不能出字（成本约 20 token）。

```
INFO:  探测模型后端可用性……
INFO:    [可用]   siliconflow     1038ms  Qwen/Qwen2.5-7B-Instruct
INFO:    [可用]   deepseek-flash  2357ms  deepseek-ai/DeepSeek-V4.1-Flash
INFO:    [可用]   ollama            93ms  qwen2.5:0.5b
INFO:    [可用]   Deepseek         481ms  deepseek-flash
INFO:  降级链：siliconflow → Deepseek → ollama → deepseek-flash
```

**注意这行链不是按延迟排的**：`ollama` 只用了 93ms（最快），却排在 `Deepseek`（481ms）后面——
因为 `providers.toml` 里写了 `priority = ["Deepseek", "ollama"]`，用户的显式意愿优先。

**请求时按链走**：一个后端重试到耗尽仍失败，就换下一个。

### 链的顺序怎么定

| 优先级 | 规则 |
|---|---|
| 1 | `default` 永远第一位 |
| 2 | `priority = [...]` 里你点名的，按你写的顺序 |
| 3 | 其余探测通过的，**按 `providers.toml` 里的段顺序** |
| 4 | 探测没通过的，排最后（只标"未验证"，**不踢掉**——探测可能误判） |

**为什么不按延迟排**：本地 0.5B 一定比云端大模型快（没有网络往返）。按延迟排会让"最快但最弱"的模型排到前面，正好和想要的相反。延迟只用来显示。

### ⚠️ 链的顺序 = 你的花钱顺序

降级是**自动的、静默的**。主后端一挂，它就按链往下试，不会问你。

| 顺位 | 后端 | 成本 |
|---|---|---|
| 1 | `siliconflow`（Qwen2.5-7B） | **免费**（开源模型） |
| 2 | `Deepseek`（官方） | 按 token 计费 |
| 3 | `ollama`（本地） | 免费，但 0.5B 较弱 |
| 4 | `deepseek-flash` | 需充值 |

**只想用免费的**：把收费的从链里去掉，或用 `priority` 把它们排到最后。

### ⚠️ 降级的代价：失败会变慢

降级用"更慢的失败"换"可能成功"：

| 场景 | 没有降级 | 有降级 |
|---|---|---|
| 主 key 错，有可用备用 | 0.7s 返回 502 | **0.7s 返回 200** ✅ |
| 主 key 错，**备用也全挂** | 0.7s 返回 502 | **最差 50s** 才 502 ❌ |
| 主慢超时（连上不响应） | 48s 返回 502 | 48s 返回 502（预算耗尽，基本不降级） |

最后一行是**故意的**：慢死的后端值得等（它还活着，只是慢），换一个不一定更快。

总预算由 `LLM_FALLBACK_BUDGET` 控制（默认 50 秒），超了就不再往下试。

### 只有一个后端时

链长 = 1，**降级逻辑完全不参与**，请求路径零额外开销。主挂了直接 502——不假装还能救。

### 实测：主 key 失效

把 `SILICONFLOW_API_KEY` 故意改错，重启服务后请求：

```
状态码          : 200
X-Provider      : Deepseek
X-Model         : deepseek-flash
X-Fallback-From : siliconflow
耗时            : 1.63 秒
```

服务端日志：

```
INFO:    [不可用] siliconflow       ——    HTTP 401
INFO:    [不可用] deepseek-flash    ——    HTTP 401
INFO:    [可用]   ollama          1554ms  qwen2.5:0.5b
INFO:    [可用]   Deepseek        1107ms  deepseek-flash
INFO:  降级链：siliconflow(未验证) → Deepseek → ollama → deepseek-flash(未验证)
WARNING:  provider siliconflow 失败（OpenAIAuthenticationError），准备降级
WARNING:  降级：切换到第 2 顺位的 Deepseek
WARNING:  降级成功：本次实际由 Deepseek 提供服务
```

**1.63 秒内，从"主后端 401"变成"用户拿到回答"。**

注意 `siliconflow` 和 `deepseek-flash` 共用一个 key，所以**两个一起挂**——降级直接把这两个都跳过了。

## ❓ 常见问题

**Q：浏览器访问 `http://0.0.0.0:6066` 打不开？**
A：`0.0.0.0` 是监听地址不是访问地址，请改用 `http://127.0.0.1:6066/docs`。

**Q：前端发消息没反应？**
A：① 确认后端已启动；② F12 看控制台是否跨域报错（后端需带 CORS 中间件）；③ 检查 `.env` 中 Key 是否有效、账户是否有余额。

**Q：前端提示「鉴权失败」(401)？**
A：前端和后端读的是同一个 `.env`，检查 `GATEWAY_API_KEY` 是否两边都读到了（改完 `.env` 要**重启**服务）；确认用 `python gradio_ui.py` 启动，而不是另外换了个工作目录。

**Q：后端返回 500 并提示「服务端未配置 GATEWAY_API_KEY」？**
A：这是 fail closed 行为，`.env` 里加上 `GATEWAY_API_KEY` 后重启即可。

**Q：流式输出卡顿/一次性蹦出？**
A：确认前端 `stream=True`，后端启动后无需额外参数，`astream` 默认流式。

## 🗺 后续可扩展方向

- [x] 请求体 Pydantic 校验
- [x] 接口鉴权
- [x] 接口测试
- [x] 上游超时与重试
- [x] 失败可见（502 而不是假 200）
- [ ] SSE 协议 + 断流时的 `event: error`
- [ ] 多供应商降级（主：大模型；备：小模型 / 本地 Ollama）
- [ ] 多会话管理（新建/切换/删除对话）
- [ ] 对话历史持久化（SQLite）
- [ ] 结构化日志与 token 用量计量
- [ ] Docker 一键部署
- [ ] 接入 RAG 知识库

完整的分阶段规划见 [docs/ROADMAP.md](docs/ROADMAP.md)。
