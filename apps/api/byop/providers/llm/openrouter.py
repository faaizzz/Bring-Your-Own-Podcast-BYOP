from decimal import Decimal, InvalidOperation

from byop.providers.common import RetryPolicy
from byop.providers.llm.base import ModelInfo
from byop.providers.llm.openai_chat import OpenAIChatProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
ONE_MILLION = Decimal(1_000_000)


def _price_per_million(value: object) -> Decimal | None:
    """OpenRouter prices are USD per token as strings; negative means 'varies' (routers)."""
    if not isinstance(value, str | int | float):
        return None
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        return None
    if price < 0:
        return None
    return (price * ONE_MILLION).quantize(Decimal("0.0001")).normalize()


class OpenRouterLLM(OpenAIChatProvider):
    name = "openrouter"
    reports_cost = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = OPENROUTER_BASE_URL,
        timeout_s: float = 120.0,
        retry: RetryPolicy | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout_s=timeout_s,
            retry=retry,
            default_headers={"X-Title": "BYOP"},
        )

    def _extra_body(self) -> dict[str, object]:
        # Ask OpenRouter to include the request's cost in `usage`.
        return {"usage": {"include": True}}

    async def list_models(self) -> list[ModelInfo]:
        payload = await self.client.get("/models", cast_to=object)
        entries = payload.get("data", []) if isinstance(payload, dict) else []
        models: list[ModelInfo] = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            raw_pricing = entry.get("pricing")
            pricing: dict[str, object] = raw_pricing if isinstance(raw_pricing, dict) else {}
            context = entry.get("context_length")
            models.append(
                ModelInfo(
                    id=entry["id"],
                    name=str(entry.get("name") or entry["id"]),
                    context_length=context if isinstance(context, int) else None,
                    prompt_price_per_million=_price_per_million(pricing.get("prompt")),
                    completion_price_per_million=_price_per_million(pricing.get("completion")),
                )
            )
        return models
