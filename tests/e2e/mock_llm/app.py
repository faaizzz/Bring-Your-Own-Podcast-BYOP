"""Stand-ins for everything BYOP talks to over the network in the end-to-end test, so the full
product can run in CI without paid keys or a GPU:

* an OpenAI-compatible chat API (`/v1/chat/completions`, `/v1/models`) that answers the ranking and
  script prompts with canned but valid JSON built from what the prompt says;
* a Kokoro-style speech API (`/v1/audio/speech`, `/v1/audio/voices`) that returns a short tone
  whose length follows the text;
* a small news feed (`/feed.xml`) with a few articles.

Run it with `uvicorn --app-dir tests/e2e/mock_llm app:app`.
"""

import json
import math
import re
import struct
import time
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request, Response

app = FastAPI(title="BYOP mock services")

SAMPLE_RATE = 24_000
SECONDS_PER_CHARACTER = 0.012  # a 10-minute script becomes a few seconds of audio
VOICES = ["af_heart", "am_michael", "af_bella", "bm_george"]

ARTICLES = [
    (
        "Open-source model gets a permissive licence",
        "A widely used open-source language model moved to a permissive licence, which lets companies ship it inside commercial products without a separate agreement.",
    ),
    (
        "New release of a popular inference server",
        "The latest release of a popular inference server roughly halves memory use for long prompts and adds support for several new model families.",
    ),
    (
        "Community benchmark compares local speech models",
        "A community benchmark compared local text-to-speech models on speed and naturalness, and found that the smallest models are now good enough for podcasts.",
    ),
    (
        "Toolkit for evaluating agents reaches version one",
        "A toolkit for evaluating AI agents reached its first stable version, with tracing built in and a simple way to replay recorded runs.",
    ),
]


def _words(count: int) -> str:
    base = (
        "that is an interesting development for anyone building with open tools because it "
        "lowers the cost of trying new ideas and keeps control in the hands of the people "
        "who run the software every day"
    ).split()
    return " ".join(base[i % len(base)] for i in range(count))


# --- chat completions ----------------------------------------------------------------------------


def _ranking(prompt: str) -> dict[str, object]:
    wanted = int(m.group(1)) if (m := re.search(r"Choose the (\d+) best stories", prompt)) else 3
    numbers = [int(n) for n in re.findall(r"^(\d+)\. ", prompt.split("Items:", 1)[-1], re.M)]
    return {
        "selections": [
            {
                "item": n,
                "score": 9 - i,
                "reason": "A relevant, well-sourced story.",
                "supporting": [],
            }
            for i, n in enumerate(numbers[:wanted])
        ]
    }


def _script(prompt: str) -> dict[str, object]:
    speakers = re.findall(r"^- \*\*(.+?)\*\*", prompt, re.M) or ["Host"]
    stories = [int(n) for n in re.findall(r"^### Story (\d+):", prompt, re.M)]
    low, high = (
        (int(m.group(1)), int(m.group(2)))
        if (m := re.search(r"between (\d+) and (\d+)\)", prompt))
        else (100, 200)
    )
    target = (low + high) // 2
    per_story = max(20, (target - 40) // max(1, len(stories)))
    lead, other = speakers[0], speakers[-1]
    segments: list[dict[str, object]] = [
        {
            "speaker": lead,
            "text": "Welcome to the show. Here is what happened today.",
            "kind": "intro",
            "item_ids": [],
        }
    ]
    for i, number in enumerate(stories):
        segments.append(
            {
                "speaker": speakers[i % len(speakers)],
                "text": f"Story {number} first. {_words(per_story // 2)}.",
                "kind": "story",
                "item_ids": [number],
            }
        )
        segments.append(
            {
                "speaker": other,
                "text": f"{_words(per_story // 2)}.",
                "kind": "story",
                "item_ids": [number],
            }
        )
    segments.append(
        {
            "speaker": lead,
            "text": "That is all for today. Thanks for listening.",
            "kind": "outro",
            "item_ids": [],
        }
    )
    return {
        "title": "Open tools, one step at a time",
        "description": "A short briefing on this week's open-source AI news, written by a mock model.",
        "segments": segments,
    }


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict[str, object]:
    body = await request.json()
    messages = body.get("messages", [])
    prompt = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "user")
    if "Choose the" in prompt and "best stories" in prompt:
        answer: dict[str, object] = _ranking(prompt)
    elif "script writer" in json.dumps(messages) or "## The speakers" in prompt:
        answer = _script(prompt)
    else:
        answer = {"candidates": [], "items": []}
    text = json.dumps(answer)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock-model"),
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}
        ],
        "usage": {
            "prompt_tokens": max(1, len(prompt) // 4),
            "completion_tokens": max(1, len(text) // 4),
            "total_tokens": max(2, (len(prompt) + len(text)) // 4),
        },
    }


@app.get("/v1/models")
async def models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": "mock-model", "object": "model", "owned_by": "mock"}]}


# --- speech --------------------------------------------------------------------------------------


@app.post("/v1/audio/speech")
async def speech(request: Request) -> Response:
    body = await request.json()
    text = str(body.get("input", ""))
    seconds = max(0.4, len(text) * SECONDS_PER_CHARACTER)
    frequency = 180 + 40 * (VOICES.index(body.get("voice")) if body.get("voice") in VOICES else 0)
    samples = int(SAMPLE_RATE * seconds)
    pcm = b"".join(
        struct.pack("<h", int(6000 * math.sin(2 * math.pi * frequency * n / SAMPLE_RATE)))
        for n in range(samples)
    )
    return Response(pcm, media_type="audio/pcm")


@app.get("/v1/audio/voices")
async def voices() -> dict[str, object]:
    return {"voices": [{"id": voice, "name": voice} for voice in VOICES]}


# --- a news feed ---------------------------------------------------------------------------------


@app.get("/feed.xml")
async def feed(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    now = datetime.now(UTC)
    items = "".join(
        f"""<item><title>{escape(title)}</title><link>{base}/articles/{n}</link>
<guid>{base}/articles/{n}</guid><pubDate>{format_datetime(now - timedelta(hours=n * 3))}</pubDate>
<description>{escape(summary)}</description></item>"""
        for n, (title, summary) in enumerate(ARTICLES, start=1)
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Open Source AI Weekly</title><link>{base}</link>
<description>Mock news for the end-to-end test</description>{items}</channel></rss>"""
    return Response(xml, media_type="application/rss+xml")


@app.get("/articles/{number}")
async def article(number: int) -> Response:
    title, summary = ARTICLES[(number - 1) % len(ARTICLES)]
    html = f"<html><head><title>{escape(title)}</title></head><body><article><h1>{escape(title)}</h1><p>{escape(summary)}</p></article></body></html>"
    return Response(html, media_type="text/html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
