from fastapi import FastAPI, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

# 初始化 FastAPI 应用
app = FastAPI(
    title="本地对话机器人 API",
    docs_url="/docs",
    redoc_url="/redoc",
    swagger_js_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui-bundle.min.js",
    swagger_css_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui.min.css"
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化大模型客户端
chat_model = ChatOpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url=os.getenv("SILICONFLOW_BASE_URL"),
    model=os.getenv("SILICONFLOW_MODEL"),
)


@app.post("/chat", summary="流式对话接口")
async def chat(
    query: str = Body(..., description="用户输入问题"),
    sys_prompt: str = Body("你是一个有用的助手", description="系统提示词"),
    history: List[dict] = Body([], description="历史对话列表"),
    history_len: int = Body(4, description="保留历史对话轮数"),
    temperature: float = Body(0.7, description="模型温度"),
    top_p: float = Body(0.9, description="top_p 采样参数"),
    max_tokens: int = Body(2048, description="最大生成长度"),
):
    # 1. 裁剪历史记录
    if history_len > 0 and len(history) > history_len * 2:
        history = history[-(history_len * 2):]

    # 2. 组装消息列表
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": query})

    # 3. 绑定模型参数（移除 streaming，astream 默认为流式）
    model = chat_model.bind(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
    )

    # 4. 异步流式生成
    async def generate_response():
        async for chunk in model.astream(messages):
            if chunk.content:
                yield chunk.content

    return StreamingResponse(generate_response(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6066, log_level="info")
