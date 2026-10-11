import gradio as gr
import requests

# 后端接口地址
BACKEND_URL = "http://127.0.0.1:6066/chat"


def chat_with_backend(prompt, history, sys_prompt, history_len, temperature, top_p, max_tokens, stream):
    # 格式化历史消息，适配后端格式
    history_formatted = [{"role": h["role"], "content": h["content"]} for h in history]

    # 构建请求参数
    data = {
        "query": prompt,
        "sys_prompt": sys_prompt,
        "history": history_formatted,
        "history_len": int(history_len),
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": int(max_tokens)
    }

    try:
        response = requests.post(BACKEND_URL, json=data, stream=True, timeout=60)
        response.raise_for_status()  # 请求失败直接抛出异常

        full_response = ""
        if stream:
            # 逐字流式输出
            for chunk in response.iter_content(chunk_size=1, decode_unicode=True):
                if chunk:
                    full_response += chunk
                    yield full_response
        else:
            # 非流式一次性返回
            full_response = response.text
            yield full_response

    except Exception as e:
        yield f"❌ 请求失败：{str(e)}"


# 构建界面
with gr.Blocks(fill_height=True, fill_width=True) as demo:
    gr.Markdown("## 本地大模型对话机器人")

    with gr.Row():
        # 左侧参数面板
        with gr.Column(scale=1, variant="panel"):
            sys_prompt = gr.Textbox(label="系统提示词", value="你是一个有用的助手", lines=3)
            history_len = gr.Slider(minimum=0, maximum=10, value=4, step=1, label="保留历史对话轮数")
            temperature = gr.Slider(minimum=0.01, maximum=2.0, value=0.7, step=0.01, label="temperature")
            top_p = gr.Slider(minimum=0.01, maximum=1.0, value=0.9, step=0.01, label="top_p")
            max_tokens = gr.Slider(minimum=512, maximum=4096, value=2048, step=8, label="max_tokens")
            stream = gr.Checkbox(label="开启流式输出", value=True)

        # 右侧聊天区域
        with gr.Column(scale=10):
            # 删掉了 type="messages" 参数
            chatbot = gr.Chatbot(height=500)
            # 删掉了 type="messages" 参数
            gr.ChatInterface(
                fn=chat_with_backend,
                chatbot=chatbot,
                additional_inputs=[
                    sys_prompt,
                    history_len,
                    temperature,
                    top_p,
                    max_tokens,
                    stream
                ]
            )

if __name__ == "__main__":
    demo.launch(server_port=7860)
