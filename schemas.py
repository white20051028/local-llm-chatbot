"""请求体的数据形状。只写"长什么样"，不写"怎么用"。

这个文件承担整个接口的第一道防线：
非法请求在进入业务函数之前就被拒掉，而且报错能精确到"哪个字段、哪种错"。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 只允许这三种角色。
# 用 Literal 而不是 str：非法值在类型层面就被拒绝，
# 不会等到拼进 messages 才发现 history 里混了一条 "root"。
Role = Literal["system", "user", "assistant"]


def _extract_text(value: object) -> str:
    """把各种「消息正文」形态统一抽成字符串。

    为什么需要这个函数：
    Gradio 6 的 ChatMessage.content 允许两种写法——字符串，
    或者内容块数组 [{"type": "text", "text": "你好"}]（为了支持多模态）。
    它的聊天记录走的正是后者，于是会出现"第一轮能聊、第二轮全挂"：
    第一轮 history 是空的，没东西可校验；第二轮把 8 条消息发上来，
    每条的 content 都是数组，全部报 Input should be a valid string。

    OpenAI 的 chat API 本来就同时接受这两种写法，所以接口兼容它们才是对的，
    不该反过来要求调用方（前端）去改。

    顺带兼容几种历史遗留形态：裸字符串数组、只带 text 键的 dict。
    遇到无法识别的（比如只有文件路径）返回空串，交给上层报"正文为空"。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content"):
            inner = value.get(key)
            if isinstance(inner, str):
                return inner
        return ""
    if isinstance(value, (list, tuple)):
        return "".join(_extract_text(item) for item in value)
    return ""


class ChatMessage(BaseModel):
    """一条历史消息。"""

    # extra="forbid"：多传了不认识的字段就报错，而不是静默忽略。
    # 这条看起来吹毛求疵，其实最救命：
    # 前端把 temperature 拼成 temprature 时，如果不 forbid，字段会被静默丢弃、
    # 模型仍然用默认值跑。你以为调了，其实没调，而且任何地方都不会报错。
    model_config = ConfigDict(extra="forbid")

    role: Role = Field(..., description="只能是 system / user / assistant")
    content: str = Field(
        ...,
        min_length=1,
        max_length=8_000,
        description='消息正文。可以是字符串，也可以是 [{"type":"text","text":"..."}] 这种内容块数组',
    )

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> str:
        """进模型之前先把 content 归一化成字符串。

        mode="before" 的意思是"在这一步校验之前先动手"：
        先接住各种形态，抽出文本，再交给 Field 去做长度检查。
        这样对外的类型仍然是 str，调用方却可以传数组。
        """
        text = _extract_text(value)
        if not text.strip():
            raise ValueError("content 不能为空（目前只支持文本消息）")
        return text


# /docs 里「Try it out」会预填这个示例。
# 必须显式给：Swagger UI 自己造示例时，对枚举取的是"第一个值"，
# 而 Role 的第一个值是 system，于是 history 被填成 [{"role": "system", ...}]，
# 正好撞上下面那条禁令 —— 结果是"照着文档点一下就 422"，非常误导人。
# 给一个一定能通过的 body，等于让文档示例变成一条隐形的测试。
EXAMPLE_REQUEST = {
    "query": "用一句话解释什么是 RAG",
    "sys_prompt": "你是一个简洁的助手",
    "history": [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你？"},
    ],
    "history_len": 4,
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 2048,
}


class ChatRequest(BaseModel):
    """POST /chat 的完整请求体。"""

    # 注意上一行的位置：docstring 必须是类体的第一条语句。
    # 如果把 model_config 写在它前面，那行字符串就不再是 docstring，
    # 只是"一句写了没用的表达式"，ChatRequest.__doc__ 会变成 None，
    # Ruff / pylint 也会警告 string statement has no effect。
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": EXAMPLE_REQUEST},
    )
    
    provider: str | None = Field(
        None,
        description="用哪个后端；不传则用服务端的默认 provider",
    )
    query: str = Field(..., min_length=1, max_length=8_000, description="用户本轮输入")
    sys_prompt: str = Field(
        "你是一个有用的助手", min_length=1, max_length=2_000, description="系统提示词"
    )
    # 为什么用 default_factory=list 而不是 = []：
    # Python 的可变默认值会在所有实例之间共享同一个列表对象，
    # 一个请求往里塞东西，下一个请求还能看到。default_factory 是每次新造一个。
    history: list[ChatMessage] = Field(
        default_factory=list, max_length=100, description="历史对话（不含本轮）"
    )
    history_len: int = Field(4, ge=0, le=10, description="保留最近几轮历史，0 表示不保留")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="采样温度")
    top_p: float = Field(0.9, gt=0.0, le=1.0, description="nucleus 采样阈值")
    max_tokens: int = Field(2048, ge=1, le=8_192, description="最大生成 token 数")

    @field_validator("history")
    @classmethod
    def _no_system_role_in_history(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        """history 里不允许出现 system 角色。

        如果不拦，调用方可以在 history 里塞一条 {"role": "system", ...}，
        路由把它原样拼进 messages 时，它就和真正的系统提示词平级，
        可以覆盖掉 sys_prompt —— 这是最廉价的一种 prompt 注入。
        堵住它只需要下面这一行判断。
        """
        if any(msg.role == "system" for msg in value):
            raise ValueError("history 中不允许出现 system 角色，系统提示词请用 sys_prompt 传")
        return value
