import json
import re

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> object:
    """Parse the JSON document in an LLM reply, tolerating code fences and surrounding prose."""
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Last resort: decode the first object/array that starts somewhere inside the text.
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[{\[]", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("No JSON document found in the reply")
