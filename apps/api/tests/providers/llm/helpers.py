import json

import httpx
import respx

from byop.providers.common import RetryPolicy

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# No sleeping in tests.
FAST_RETRY = RetryPolicy(max_attempts=3, initial_wait_s=0.0, max_wait_s=0.0)


def completion(
    content: str,
    *,
    model: str = "test/model",
    prompt: int = 10,
    completion_tokens: int = 5,
    cost: float | str | None = None,
) -> dict[str, object]:
    usage: dict[str, object] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt + completion_tokens,
    }
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": usage,
    }


def body_of(route: respx.Route, call: int = -1) -> dict[str, object]:
    request: httpx.Request = route.calls[call].request
    return json.loads(request.content)  # type: ignore[no-any-return]
