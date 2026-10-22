from pydantic import ValidationError

from schemas import ChatRequest

print("① 最小合法：", ChatRequest.model_validate({"query": "hi"}).temperature)

for bad in [
    {"query": "hi", "temperature": 9},
    {"query": "hi", "history": [{"role": "root", "content": "x"}]},
    {"query": ""},
    {"query": "hi", "foo": 1},
]:
    try:
        ChatRequest.model_validate(bad)
        print("② 竟然通过了！", bad)
    except ValidationError as e:
        print("② 被拦住：", e.errors()[0]["loc"], "→", e.errors()[0]["msg"])