"""DashScope (OpenAI-compatible) chat call, the same request shape as the main game's MT runs."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from common import load_env

MODEL = "deepseek-v4.1-flash"


@dataclass
class Call:
    text: str
    model: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    elapsed: float


def chat(messages: list[dict], *, model: str = MODEL, thinking: bool = False, max_tokens: int = 16000,
         timeout: float = 900.0, attempts: int = 3) -> Call:
    base_url, key = load_env()
    payload = dict(model=model, messages=messages, temperature=0.1, max_tokens=max_tokens,
                   enable_thinking=thinking, response_format={"type": "json_object"}, stream=False)
    if thinking:  # the JSON mode is not accepted together with thinking
        payload.pop("response_format")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = None
    for attempt in range(attempts):
        request = Request(base_url + "/chat/completions", data=body, method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"})
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=timeout) as response:
                doc = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            last = RuntimeError(f"DashScope HTTP {exc.code}: {detail}")
            if exc.code not in (429, 500, 502, 503, 504):
                raise last from exc
        except (OSError, URLError, json.JSONDecodeError) as exc:
            last = RuntimeError(f"DashScope request failed: {exc}")
        else:
            choice = doc["choices"][0]
            usage = doc.get("usage") or {}
            return Call(
                text=choice["message"].get("content") or "",
                model=doc.get("model", model),
                finish_reason=choice.get("finish_reason"),
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cached_tokens=int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                reasoning_tokens=int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
                elapsed=time.perf_counter() - started,
            )
        time.sleep(5 * (attempt + 1))
    raise last


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])
