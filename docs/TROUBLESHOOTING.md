# 踩坑记录：把一个 demo 改成能用的服务

这次改造总共 `+694 / -54` 行，但真正花时间的不是写代码，而是**六个"我以为它应该是那样"的假设**。

每个坑按同一格式记录：现象 → 怎么查出来的 → 根因 → 修法 → 怎么验证 → 一句话教训。

## 速查表

| # | 现象 | 根因（一句话） | 对应提交 |
|---|---|---|---|
| 1 | 环境变量没配时，422 全变成 500 | 抛的是 pydantic 的 `ValidationError`，不是 `HTTPException` | `7544d8a` |
| 2 | 照着 `/docs` 点一下就 422 | Swagger UI 对枚举取第一个值，把 `history` 预填成 `role="system"` | `7715615` |
| 3 | 网页聊天第一轮正常，第二轮必挂 | Gradio 6 的 `content` 是内容块数组，不是字符串 | `41d5426` |
| 4 | 跑完测试仓库里多出 `.pytest_cache/` | `.gitignore` 没覆盖 | `67ee9bf` |
| 5 | `ssh git@github.com` 报 `Unknown error` | hosts 被加速工具劫持到 `127.0.0.1` | — |
| 6 | GitHub token 明文躺在 `.git/config` | 令牌被写进了 remote URL | — |

---

## 坑 1：配置缺失时，客户端错误被报成服务器错误

**现象**
`.env` 里没填 `SILICONFLOW_API_KEY` 等三个变量时，任何发到 `/chat` 的请求都返回 500，而且日志只有一行看不懂的东西：

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for ChatOpenAI
model
  Input should be a valid string [type=string_type, input_value=None]
```

**怎么查出来的**
18 个单测全绿，但起了真服务再打一遍，三个本该 422 的请求全变 500。差别在于单测里用 `dependency_overrides` 把模型换成了假的，**从来没碰过真实配置**。

**根因**
两件事叠在一起：
1. `ChatOpenAI(...)` 拿到 `None` 会抛 pydantic 的 `ValidationError`，而不是 `HTTPException`，FastAPI 兜底成 500；
2. **FastAPI 先解依赖、再校验请求体**，所以这个 500 会盖住本该出现的 422。

**修法**
在 `get_model()` 里显式检查必需的环境变量，缺了就抛一个说人话的 `HTTPException(500)`：

```python
missing = [key for key in MODEL_ENV_KEYS if not os.getenv(key)]
if missing:
    raise HTTPException(500, detail=f"服务端缺少配置：{', '.join(missing)}，请检查 .env 后重启服务")
```

**怎么验证**
```powershell
curl.exe -s -X POST http://127.0.0.1:6066/chat `
  -H "Content-Type: application/json" -H "X-API-Key: 你的key" -d "{}"
# 期望：{"detail":"服务端缺少配置：SILICONFLOW_API_KEY, ..."}
```

**教训**
500 的文案也是接口的一部分。留一个"依赖先于校验"的顺序问题（服务端自己坏了，任何请求都该先报服务端坏了），但把文案做到十秒能定位——比调整顺序更有价值。

---

## 坑 2：文档示例本身不合法

**现象**
启动服务、打开 `/docs`、点 **Try it out**、填好 API Key、Execute —— 422：

```json
{"detail":[{"field":"history","reason":"Value error, history 中不允许出现 system 角色，系统提示词请用 sys_prompt 传"}]}
```

**怎么查出来的**
把 `/openapi.json` 打出来看 `ChatMessage.role`：

```json
"enum": ["system", "user", "assistant"]
```

**根因**
Swagger UI 生成请求体示例时，对枚举**取第一个值**。`system` 排在第一位，于是它把 `history` 自动填成：

```json
"history": [{"role": "system", "content": "string"}]
```

而 `history` 里禁 `system` 正是为了防止 prompt 注入 —— **校验规则和文档示例打架**，文档让你点的第一个按钮就是错的。

**修法**
给模型一个显式的、一定合法的示例，文档就不靠 Swagger 猜了：

```python
model_config = ConfigDict(extra="forbid", json_schema_extra={"example": EXAMPLE_REQUEST})
```

再加一条测试，把"示例必须合法"钉死：

```python
schema = app.openapi()["components"]["schemas"]["ChatRequest"]
ChatRequest.model_validate(schema["example"])          # 示例能被模型接受
assert client.post("/chat", json=schema["example"]).status_code == 200
```

**教训**
**文档示例要当测试用。** 你自己写的校验，很可能第一个卡住的就是你自己的文档。

---

## 坑 3：网页聊天第一轮能用，第二轮必挂（最有教学价值的一个）

**现象**
Gradio 页面里第一句能正常回，第二句开始报：

```
❌ 参数校验未通过：[{'field': 'history.0.content', 'reason': 'Input should be a valid string'},
                    {'field': 'history.1.content', ...}, ... 共 8 条]
```

8 条 = 4 轮对话的 8 条消息，一条不落全报了。

**怎么查出来的**
先按形状逐个试探，复现出**逐字相同**的报错：

| 传进去的 content | 结果 |
|---|---|
| `"你好"` | 200 |
| `[{"type":"text","text":"你好"}]` | **422，报错同截图** |
| `{"text":"你好"}` | 422 |
| `null` | 422 |

再翻 Gradio 6.30 的源码确认。`ChatMessage.content` 的官方类型是**字符串或内容块数组**，而且 `chat_interface.py` 自己在遍历它：

```python
for content in message["content"]:
    if content["type"] == "text":
        title += content["text"]
```

**根因**
Gradio 6 用「内容块数组」表示一条消息（为了支持多模态），所以 `history` 里每条 `content` 都是 `[{"type":"text","text":"..."}]`。
第一轮之所以能过，纯粹是因为 `history` 是空的。

**修法**
不是去改前端"把数组拆成字符串"，而是让**后端两种都接受**——OpenAI 的 chat API 本来就是这样设计的，作为"OpenAI 兼容网关"兼容它才是对的：

```python
@field_validator("content", mode="before")
@classmethod
def _normalize_content(cls, value: object) -> str:
    text = _extract_text(value)      # 数组 / dict / 字符串 → 统一抽成字符串
    if not text.strip():
        raise ValueError("content 不能为空（目前只支持文本消息）")
    return text
```

`_extract_text` 覆盖四种形态：`"你好"`、`[{"type":"text","text":"你好"}]`、`["你","好"]`（Gradio 多模态分支会直接 append 字符串）、`{"text":"你好"}`。

**怎么验证**
```python
body = {"query": "第五问", "history": 4轮8条的content块数组, "history_len": 4}
# 修复后：200；归一化后发给模型的是 ['问0','答0',...,'问3','答3']
```

**教训**
这是三个坑里最值得讲的一个：**单测全绿，是因为我一直用"我自己想象的形状"在测。**
回归测试必须用真实调用方的格式写——现在测试里有一条就是"模拟 Gradio 聊到第 4 轮"。

---

## 坑 4：测试产物混进版本库

**现象**：跑完 `pytest`，`git status` 里多出 `.pytest_cache/`。

**根因**：`.gitignore` 写了 `__pycache__/`，但没写 `.pytest_cache/`。

**修法**：
```gitignore
# ===== 测试 =====
.pytest_cache/
.coverage
htmlcov/
```

**教训**：装了新工具，顺手更新 `.gitignore`。这类文件一旦提交，后面每次都要解释一遍。

---

## 坑 5（环境）：`ssh git@github.com` 报 `Unknown error`

**现象**
```
ssh: connect to host github.com port 22: Unknown error
```

**怎么查出来的**
```powershell
Resolve-DnsName github.com      # → 127.0.0.1   ← 不对
Test-NetConnection github.com -Port 22   # → False
Test-NetConnection ssh.github.com -Port 443  # → True
```

**根因**
本机 hosts 文件被加速工具（Steam++ / Watt Toolkit，`local.steampp.net` 那条自报家门）写入了上百条 `127.0.0.1 <域名>`，包括 `github.com`。它只在本地开了 443 做网页反代，**没开 22**，所以 SSH 连到 127.0.0.1:22 被拒，Windows 的 ssh 把"连接被拒"翻译成了那句含糊的 `Unknown error`。

**修法**
在 `~/.ssh/config` 里让 github.com 这个名字走 `ssh.github.com:443`（真实 IP，不受 hosts 影响）：

```
Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/id_ed25519
  IdentityFile ~/.ssh/id_rsa
  StrictHostKeyChecking accept-new
```

**教训**
`Unknown error` 不是网络差，是**域名解析到哪儿**的问题。先 `Resolve-DnsName`，比反复重试有效。

---

## 坑 6（安全）：token 明文写在 remote URL 里

**现象**：`.git/config` 里是

```
[remote "origin"]
    url = https://ghp_xxxxxxxx@github.com/user/repo.git
```

**怎么查出来的**
```powershell
git -C . log -p --all | Select-String "ghp_"   # 提交历史里 0 命中
git -C . remote -v                             # remote 里 2 处命中
```

**影响范围**：token 没有进提交历史，所以**没有推到公开仓库**；但它明文躺在本地 `.git/config` 里，只要目录被同步、压缩、分享就会泄露，而它的权限是该仓库的完整读写。

**修法**
1. 立刻到 GitHub / Gitee 后台**撤销**这两个 token（删掉不等于过期）；
2. 重新生成时设 90 天过期；
3. 改用 SSH，`git remote set-url origin git@github.com:...`；
4. 以后 token 只放环境变量或凭据管理器，**永不写进 URL**。

**教训**
"没被提交"不等于"没泄露"。凭证的第一原则是：**它不该出现在任何会被复制的文件里**。

---

## 环境备注

| 项 | 版本 |
|---|---|
| Python | 3.14.7 |
| FastAPI | 0.143.0 |
| Pydantic | 2.14.0 |
| Gradio | 6.30.0 |
| pytest | 9.1.1 |

---

## 面试可以怎么讲这三个坑

**"你项目里最有挑战的问题是什么？"**

> 我做了个 LLM 对话服务，上线前发现只要用户聊到第二轮就全部 422。
> 第一轮正常、第二轮全挂，说明问题一定出在 history 上。
> 我把 history 里 `content` 的几种可能形状逐个打了一遍，复现出完全相同的报错，
> 再去翻 Gradio 源码，确认它 6.0 之后把消息正文改成了"内容块数组"来支持多模态。
> 我没有在前端拆数组，而是在后端把 `content` 做成兼容字符串和数组两种形态——
> 因为 OpenAI 的 chat API 本来就是这么设计的，作为兼容网关应该跟着协议走。
> 修完我补了一条"模拟聊到第 4 轮"的回归测试，
> 因为之前单测全绿没发现，是我一直用自己想象的格式在测。

**要点**：症状 → 缩小范围 → 复现 → 读源码确认 → 选"跟协议走"而不是"打补丁" → 补回归测试 → 反思测试方法。

---

## 一条方法论

这六个问题里有三个（1、2、3）是同一类：**边界上的格式假设**。

- 我以为配置总是齐全的
- 我以为调用方会照我写的文档传
- 我以为 content 是字符串

而单测之所以全绿，是因为我在用**自己的假设**验证**自己的假设**。

对策只有一条：**每个接口的最后一条测试，要用真实调用方的真实格式写一遍。**
