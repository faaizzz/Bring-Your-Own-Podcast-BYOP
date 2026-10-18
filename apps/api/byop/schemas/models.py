from decimal import Decimal

from pydantic import BaseModel


class ModelResponse(BaseModel):
    id: str
    name: str
    context_length: int | None = None
    # USD per one million tokens; None when the provider does not publish a price.
    prompt_price_per_million: Decimal | None = None
    completion_price_per_million: Decimal | None = None
