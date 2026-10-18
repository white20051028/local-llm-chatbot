"""请求体模型（Pydantic v2）。

为什么值得单独开一个文件：
原来接口是 `query: str = Body(...)`、`history: List[dict] = Body([])` 这样一个个声明的。
它有三个问题：

1. `List[dict]` 接受任何字典——role 写成 "root"、"system" 塞进 history、
   缺 content 字段，全都放行。这些脏数据要等到调用大模型时才炸，
   而且是以 500（服务器错误）的形式炸，你会以为是自己服务挂了。
2. 没有任何上下界。用户传 temperature=999、max_tokens=-1，一样放行。
3. 接口文档里看不出约束，前端只能靠猜。

用模型定义之后，FastAPI 会在**进入函数之前**完成校验，
非法请求直接返回 422 并指出是哪个字段错了，函数体里拿到的都是已确定合法的数据。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 只允许这三种角色。Litertal 让非法值在类型层面就被拒绝。
Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """一条历史消息。"""

    # extra="forbid"：多传了不认识的字段就报错，而不是静默忽略。
    # 这能挡住前端拼错字段名（比如把 role 写成 roles）后悄悄失效的情况。
    model_config = ConfigDict(extra="forbid")

    role: Role = Field(..., description="只能是 system / user / assistant")
    content: str = Field(..., min_length=1, max_length=8_000, description="消息正文")


class ChatRequest(BaseModel):
    """POST /chat 的完整请求体。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=8_000, description="用户本轮输入")
    sys_prompt: str = Field(
        "你是一个有用的助手", max_length=2_000, description="系统提示词"
    )
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

        为什么这条重要：如果把 history 里的 system 原样拼进 messages，
        调用方就能在同一次请求里伪造一条 system 指令，覆盖掉 sys_prompt。
        这是最廉价的一种 prompt 注入，堵住它只需要一行校验。
        """
        if any(msg.role == "system" for msg in value):
            raise ValueError("history 中不允许出现 system 角色，系统提示词请用 sys_prompt 传")
        return value
