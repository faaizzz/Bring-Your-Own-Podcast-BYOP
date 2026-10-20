"""A minimum delay between requests to one provider, shared by every worker.

Some providers allow only a few requests per minute, and a run that makes many calls (a script
for every story, a clip for every line) would be answered with HTTP 429. With "wait N seconds
between requests" set on a provider (or a connection), each request first reserves the next free
moment in Redis, atomically, and sleeps until then, so concurrent tasks and several Celery
workers queue up instead of racing. Redis trouble never stops a run: the request goes out
without waiting (like the login rate limit).
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from byop.config import get_settings
from byop.providers.common import Throttle, record_notice
from byop.services.credentials import ProviderConfig

log = structlog.get_logger(__name__)

MAX_INTERVAL_S = 60.0
# Waits shorter than this are not worth a line in the run log.
NOTICE_THRESHOLD_S = 0.5

# Reserve the next free slot: it starts now, or when the previous reservation's interval is over.
# Redis' own clock keeps workers on different machines in step. Returns the milliseconds to wait.
_RESERVE = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local interval = tonumber(ARGV[1])
local free = tonumber(redis.call('GET', KEYS[1]) or '0')
local start = now
if free > now then start = free end
redis.call('SET', KEYS[1], start + interval, 'PX', (start - now) + interval + 5000)
return start - now
"""

DISPLAY_NAMES = {
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
    "elevenlabs": "ElevenLabs",
    "kokoro": "Kokoro",
}


@dataclass
class RequestThrottle:
    """`wait()` before each request to the provider named by `key`."""

    key: str
    interval_s: float
    label: str
    redis_url: str
    # Where the wait is announced, besides the log (the run's log through the usage sink).
    notify: Callable[[str], None] = record_notice

    async def wait(self) -> float:
        # A connection of our own: workers run in event loops that come and go.
        redis = Redis.from_url(self.redis_url, socket_connect_timeout=2, socket_timeout=5)
        try:
            wait_ms = int(
                await redis.eval(_RESERVE, 1, self.key, str(round(self.interval_s * 1000)))
            )
        except (RedisError, OSError, ValueError) as exc:
            log.warning("throttle_unavailable", provider=self.label, error=type(exc).__name__)
            return 0.0
        finally:
            await redis.aclose()

        seconds = wait_ms / 1000
        if seconds <= 0:
            return 0.0
        if seconds >= NOTICE_THRESHOLD_S:
            message = f"Waiting {seconds:.1f} s for the {self.label} rate limit"
            log.info("throttle_wait", provider=self.label, seconds=round(seconds, 2))
            self.notify(message)
        await asyncio.sleep(seconds)
        return seconds


def throttle_for(config: ProviderConfig) -> Throttle | None:
    """The throttle of a resolved provider, or None when it has no wait set."""
    if config.min_interval_s <= 0 or config.throttle_key is None:
        return None
    label = config.label or DISPLAY_NAMES.get(config.provider.value, config.provider.value)
    return RequestThrottle(
        key=config.throttle_key,
        interval_s=min(config.min_interval_s, MAX_INTERVAL_S),
        label=label,
        redis_url=get_settings().redis_url,
    )
