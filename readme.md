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

## 📂 项目结构

```
.
├── fastapi_bot.py        # 后端：路由、模型客户端、异常处理
├── schemas.py            # 请求体模型（Pydantic），负责字段与上下界校验
├── auth.py               # API Key 鉴权依赖
├── gradio_ui.py          # 前端：Gradio 聊天界面与参数面板
├── tests/
│   └── test_api.py       # 接口测试（pytest）
├── pytest.ini            # pytest 配置
├── requirements.txt      # 运行时依赖
├── requirements-dev.txt  # 开发/测试依赖
├── .env.example          # 环境变量模板
├── .env                  # 本地配置（不提交 Git）
└── .gitignore
```

## ⚙️ 切换模型/服务

由于走的是 OpenAI 兼容协议，切换模型只需要改 `.env`：
- **本地 Ollama**：`SILICONFLOW_BASE_URL=http://localhost:11434/v1`，`SILICONFLOW_MODEL=qwen2.5:7b`
- **vLLM 自建服务**：指向你的 vLLM 地址即可
- **其他 OpenAI 兼容服务**：填入对应地址与模型名

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
- [ ] 对话历史持久化（SQLite）
- [ ] Docker 一键部署
- [ ] 多会话管理（新建/切换/删除对话）
- [ ] 上游超时、重试与多供应商降级
- [ ] 结构化日志与 token 用量计量
- [ ] 接入 RAG 知识库
