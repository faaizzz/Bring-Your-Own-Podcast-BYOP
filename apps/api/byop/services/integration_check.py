"""Cheap live calls that prove a provider configuration works (list models/voices, auth check)."""

from dataclasses import dataclass

import httpx

from byop.models.enums import CredentialProvider
from byop.services.credentials import ProviderConfig

TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


def _request(config: ProviderConfig) -> tuple[str, dict[str, str], tuple[str, str] | None]:
    """URL, headers and optional basic auth of the probe for this provider."""
    key = config.api_key.get_secret_value() if config.api_key else None
    bearer = {"Authorization": f"Bearer {key}"} if key else {}
    base = (config.base_url or "").rstrip("/")
    match config.provider:
        case CredentialProvider.OPENROUTER:
            return "https://openrouter.ai/api/v1/auth/key", bearer, None
        case CredentialProvider.OPENAI:
            return f"{base or 'https://api.openai.com/v1'}/models", bearer, None
        case CredentialProvider.ELEVENLABS:
            return "https://api.elevenlabs.io/v1/models", {"xi-api-key": key or ""}, None
        case CredentialProvider.LANGFUSE:
            public = config.extra.get("public_key", "")
            return f"{base}/api/public/projects", {}, (public, key or "")
        case CredentialProvider.KOKORO:
            return f"{base}/audio/voices", {}, None
        case CredentialProvider.OPENAI_COMPATIBLE:
            return f"{base}/models", bearer, None


async def check_provider(config: ProviderConfig) -> CheckResult:
    """Probe the provider. Details are safe to show: no URLs, bodies or secrets."""
    url, headers, basic = _request(config)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.get(
                url, headers=headers, auth=httpx.BasicAuth(*basic) if basic else None
            )
    except httpx.TimeoutException:
        return CheckResult(False, "The provider did not answer in time")
    except httpx.HTTPError as exc:
        return CheckResult(False, f"Could not connect ({type(exc).__name__})")

    if response.is_success:
        return CheckResult(True, "Connection works")
    if response.status_code in (401, 403):
        return CheckResult(False, f"Authentication failed (HTTP {response.status_code})")
    return CheckResult(False, f"Unexpected response (HTTP {response.status_code})")
