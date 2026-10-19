"""Stand-ins for everything BYOP talks to over the network in the end-to-end test, so the full
product can run in CI without paid keys or a GPU:

* an OpenAI-compatible chat API (`/v1/chat/completions`, `/v1/models`) that answers the ranking and
  script prompts with canned but valid JSON built from what the prompt says;
* a Kokoro-style speech API (`/v1/audio/speech`, `/v1/audio/voices`) that returns a short tone
  whose length follows the text;
* a small news feed (`/feed.xml`) with a few articles, and a fuller one (`/demo-feed.xml`) that the
  documentation screenshots use.

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
    numbers = [int(n) for n in re.findall(r"^\[(\d+)\] ", prompt.split("Items:", 1)[-1], re.M)]
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


REACTIONS = [
    "That matters because it lowers the cost of trying things out, and it keeps the control "
    "with the people who actually run the software.",
    "What stands out is how quickly this went from an idea to something people can use today.",
    "It is a good reminder that the boring parts, like licences and packaging, decide what gets "
    "adopted.",
    "If you build with open tools, this is worth an afternoon of your time.",
    "The details are worth reading, but the direction is clear and it is a welcome one.",
]


def _stories(prompt: str) -> list[tuple[int, str, str]]:
    """(number, title, summary) of every story in the script prompt."""
    found = re.findall(
        r"^### Story (\d+): (.+?)\n\nSource: .*?\n\n(.*?)(?=\n\n|\Z)", prompt, re.M | re.S
    )
    return [(int(n), title.strip(), summary.strip()) for n, title, summary in found]


def _speech(lead: str, words: int, offset: int) -> str:
    """Natural-sounding text of about `words` words: `lead`, then reactions until it is long
    enough, ending on a full sentence where that costs little length."""
    sentences = [s.strip() for s in re.findall(r"[^.!?]+[.!?]", lead)] or [lead]
    i = offset
    text = ""
    while len(text.split()) < words:
        text = " ".join([*sentences, REACTIONS[i % len(REACTIONS)]]) if i == offset else (
            text + " " + REACTIONS[i % len(REACTIONS)]
        )
        i += 1
    if len(text.split()) <= words + 8:
        return text
    cut = " ".join(text.split()[:words])
    stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    # A full sentence if that keeps at least 70% of the length; otherwise cut at the word.
    return cut[: stop + 1] if stop > 0 and stop >= len(cut) * 0.7 else cut + "."


def _script(prompt: str) -> dict[str, object]:
    speakers = re.findall(r"^- \*\*(.+?)\*\*", prompt, re.M) or ["Host"]
    stories = _stories(prompt)
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
            "text": "Welcome back. Here is what we are following today.",
            "kind": "intro",
            "item_ids": [],
        }
    ]
    for i, (number, title, summary) in enumerate(stories):
        segments.append(
            {
                "speaker": speakers[i % len(speakers)],
                "text": _speech(f"{title}. {summary}", per_story // 2, i),
                "kind": "story",
                "item_ids": [number],
            }
        )
        segments.append(
            {
                "speaker": other,
                "text": _speech(REACTIONS[(i + 1) % len(REACTIONS)], per_story // 2, i + 2),
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
    headline = stories[0][1].rstrip(".") if stories else "This week in open tools"
    more = f", plus {len(stories) - 1} more" if len(stories) > 1 else ""
    return {
        "title": f"{headline}{more}",
        "description": "In this episode: " + "; ".join(t for _, t, _ in stories) + ".",
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


DEMO_ARTICLES = [
    ("Open-weights model family adds a 3B variant that runs on laptops", "The new variant keeps most of the larger model's quality on everyday tasks and fits in eight gigabytes of memory, so it runs on an ordinary laptop without a GPU."),
    ("Inference server ships speculative decoding by default", "The latest release turns on speculative decoding out of the box, which the maintainers say cuts latency for chat workloads by roughly a third."),
    ("Local speech models close the gap with hosted voices in a listening test", "In a blind listening test, a small open text-to-speech model was rated almost as natural as a leading hosted service for narration."),
    ("Evaluation toolkit for agents reaches its first stable release", "Tracing, replayable runs and a simple scoring API are part of the first stable version, aimed at teams that want to test agents before shipping them."),
    ("A permissive licence for a widely used language model", "The authors moved the model to a permissive licence, so companies can build it into commercial products without negotiating a separate agreement."),
    ("Vector database adds hybrid search with one flag", "Keyword and semantic search can now be combined in a single query, which the project says improves results for short, specific questions."),
    ("Open dataset of podcast transcripts released for research", "Thousands of hours of openly licensed podcast transcripts were published with speaker labels, to help researchers build better speech tools."),
    ("Browser runtime brings small models to the web without a server", "A new runtime executes small language models directly in the browser using the graphics card, which makes private, offline demos practical."),
    ("Guide: running a home model server on a single mini PC", "A step-by-step guide shows how to serve a handful of open models from one inexpensive machine, with notes on power use and noise."),
    ("Fine-tuning library halves memory use for long documents", "A new release lets people fine-tune on long documents with about half the memory, at a small cost in speed."),
    ("Community maintains a free index of open models and their licences", "Volunteers keep a searchable index of open models, their sizes and their licences, updated every week."),
    ("Speech-to-text model adds streaming for live captions", "The open model now transcribes in real time with low delay, which makes live captions for talks and meetings possible on modest hardware."),
]


@app.get("/demo-feed.xml")
async def demo_feed(request: Request) -> Response:
    """A fuller feed for the documentation screenshots: enough fresh stories for a few episodes."""
    base = str(request.base_url).rstrip("/")
    now = datetime.now(UTC)
    items = "".join(
        f"""<item><title>{escape(title)}</title><link>{base}/demo-articles/{n}</link>
<guid>{base}/demo-articles/{n}</guid><pubDate>{format_datetime(now - timedelta(hours=n * 2))}</pubDate>
<description>{escape(summary)}</description></item>"""
        for n, (title, summary) in enumerate(DEMO_ARTICLES, start=1)
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Open Source AI Weekly</title><link>{base}</link>
<description>News about open-source AI tooling</description>{items}</channel></rss>"""
    return Response(xml, media_type="application/rss+xml")


@app.get("/demo-articles/{number}")
async def demo_article(number: int) -> Response:
    title, summary = DEMO_ARTICLES[(number - 1) % len(DEMO_ARTICLES)]
    html = f"<html><head><title>{escape(title)}</title></head><body><article><h1>{escape(title)}</h1><p>{escape(summary)}</p></article></body></html>"
    return Response(html, media_type="text/html")


@app.get("/articles/{number}")
async def article(number: int) -> Response:
    title, summary = ARTICLES[(number - 1) % len(ARTICLES)]
    html = f"<html><head><title>{escape(title)}</title></head><body><article><h1>{escape(title)}</h1><p>{escape(summary)}</p></article></body></html>"
    return Response(html, media_type="text/html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
