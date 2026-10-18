import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAX_URL_LENGTH = 2048

# Parameters that identify a campaign or a click, not the page.
_TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "dclid", "msclkid", "yclid", "twclid", "igshid", "mc_cid", "mc_eid",
        "ref", "ref_src", "ref_url", "_hsenc", "_hsmi", "cmpid", "spm", "mkt_tok", "oly_enc_id",
        "vero_id", "s_cid", "ncid", "ocid", "cid", "taid", "source", "feature",
    }
)  # fmt: skip
_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_url(url: str) -> str | None:
    """One stable spelling per page, or None if `url` is not a usable http(s) address.

    Lower-cases the host and drops `www.`, default ports, fragments, tracking parameters
    (`utm_*`, `fbclid`, ...) and a trailing slash, sorts the remaining parameters, and treats
    http and https as the same page.
    """
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    host = host.removeprefix("www.")
    netloc = host if port in (None, _DEFAULT_PORTS[parts.scheme.lower()]) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=False)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
        )
    )
    canonical = urlunsplit(("https", netloc, path, query, ""))
    return canonical if len(canonical) <= MAX_URL_LENGTH else None


def normalise_text(text: str) -> str:
    return " ".join(text.casefold().split())


def content_hash(title: str, summary: str) -> str:
    """Identifies a story by its words, so the same text under two URLs is recognised."""
    basis = f"{normalise_text(title)}\n{normalise_text(summary)[:300]}"
    return hashlib.sha256(basis.encode()).hexdigest()
