"""Provider keys are read only by the credential resolver (see byop/services/credentials.py)."""

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "byop"
ALLOWED = {PACKAGE / "services" / "credentials.py", PACKAGE / "config.py"}
KEY_FIELDS = re.compile(
    r"\b(openrouter_api_key|openai_api_key|elevenlabs_api_key|langfuse_public_key|"
    r"langfuse_secret_key|kokoro_base_url)\b"
)


def test_no_module_other_than_the_resolver_reads_provider_keys() -> None:
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if path not in ALLOWED and KEY_FIELDS.search(path.read_text())
    ]

    assert offenders == [], f"read provider keys via CredentialResolver instead: {offenders}"
