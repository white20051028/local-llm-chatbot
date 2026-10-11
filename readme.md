# 本地调用api大模型多轮对话机器人

> 一个前后端分离的流式对话 Web 应用：FastAPI 后端对接 OpenAI 兼容的大模型 API（硅基流动 / Ollama / vLLM 均可），Gradio 前端提供聊天交互与参数调节面板。

## ✨ 功能特性

- **流式逐字输出**：基于 LangChain 原生 `astream()`，打字机效果实时渲染
- **多轮上下文记忆**：可调节保留的历史对话轮数，自动裁剪超长上下文
- **参数可视化调节**：温度、top_p、max_tokens、系统提示词全部支持滑块实时调整
- **前后端分离**：FastAPI 提供流式接口，Gradio 作为前端，可独立替换/扩展
- **配置与代码分离**：API Key、模型、地址全部通过 `.env` 管理，代码零敏感信息
- **CORS 跨域支持**：前后端分离部署无跨域问题

## 🛠 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn |
| 大模型调用 | LangChain / langchain-openai（兼容 OpenAI 协议） |
| 前端界面 | Gradio |
| 环境管理 | python-dotenv |
| 模型接入 | 任意 OpenAI 兼容接口（硅基流动、Ollama、vLLM、OpenAI 等） |

## 🏗 请求链路

```
用户(Gradio 前端 :7860)
   │  POST /chat (JSON: query + history + 参数)
   ▼
FastAPI 后端 (:6066)
   │  1. 裁剪历史记录
   │  2. 组装 system + history + user 消息
   │  3. ChatOpenAI.bind(参数).astream(messages)
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

## 📂 项目结构

```
.
├── fastapi_bot.py      # 后端：FastAPI 流式对话接口
├── gradio_ui.py        # 前端：Gradio 聊天界面与参数面板
├── requirements.txt    # 依赖清单
├── .env.example        # 环境变量模板
├── .env                # 本地配置（不提交 Git）
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

**Q：流式输出卡顿/一次性蹦出？**
A：确认前端 `stream=True`，后端启动后无需额外参数，`astream` 默认流式。

## 🗺 后续可扩展方向

- [ ] 对话历史持久化（SQLite）
- [ ] Docker 一键部署
- [ ] 多会话管理（新建/切换/删除对话）
- [ ] 异常重试与日志记录
- [ ] 接入 RAG 知识库
