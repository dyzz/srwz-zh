#!/usr/bin/env python3
"""Translate one story-dialogue stage through Alibaba Cloud Qwen-MT.

The command is deliberately a review-only producer.  It reads the ignored
story-dialogue queue, sends small same-section groups through Qwen-MT, checks
that XML segment IDs survive exactly, normalizes only mechanical punctuation
and layout artifacts, and validates every returned row with the existing
fail-closed importer.  Checkpoints, raw responses, and the final model output
stay below ``work/``; nothing is promoted to the release corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

try:
    from srwz.diagnostics import require_work_output
    from srwz.translation_review import TranslationReviewError
except ModuleNotFoundError:  # pragma: no cover - direct checkout invocation
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.translation_review import TranslationReviewError

try:
    from import_story_dialogue_local_model_batch import (
        _validate_translation,
        load_queue,
        validate_model_output,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.import_story_dialogue_local_model_batch import (
        _validate_translation,
        load_queue,
        validate_model_output,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_INPUT = WORK_ROOT / "review" / "local-model" / "story-dialogue-unique.jsonl"
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_MODEL = "qwen-mt-plus"
DEFAULT_BATCH_SIZE = 8
DEFAULT_WORKERS = 4
DEFAULT_RPM = 30.0
DEFAULT_TIMEOUT = 45.0
DEFAULT_NETWORK_ATTEMPTS = 3
DEFAULT_DOMAIN = (
    "Japanese dialogue from a tactical robot anime role-playing game. "
    "Translate into concise, natural Simplified Chinese suitable for in-game "
    "dialogue. Preserve XML tags, character voice, proper nouns, punctuation, "
    "line breaks, and control tokens. Do not add explanations."
)

_SEGMENT_PATTERN = re.compile(
    r'<srwz-seg\s+id=["\'](\d+:\d+)["\']>\s*(.*?)\s*</srwz-seg>',
    re.DOTALL,
)
_ASCII_QUOTES = re.compile(r'"([^"\n]*)"')
_PUNCT_SPACE = re.compile(r"\s+([，。！？；：、,.!?;:…])")
_PUNCT_TRAILING_SPACE = re.compile(r"([，。！？；：、,.!?;:…])\s+")
_CLOSE_SPACE = re.compile(r"\s+([”’）》】〕〉])")
_OPEN_SPACE = re.compile(r"([“‘《【〔〈])\s+")
_DUPLICATE_SPACE = re.compile(r"[ \t]{2,}")
_CJK_SPACE = re.compile(
    r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF·]) +"
    r"(?=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF·])"
)
_CJK_PUNCT_SPACE = re.compile(
    r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF·]) +"
    r"(?=[，。！？；：、,.!?;:…])"
)
_LATIN_CJK_SPACE = re.compile(
    r"(?:(?<=[A-Za-z0-9]) +(?=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF])"
    r"|(?<=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF]) +(?=[A-Za-z0-9]))"
)
_JAPANESE_LEXICAL_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFFぁ-んァ-ヶー]")
_TARGET_SIMPLIFICATIONS = {"破砕": "破碎"}


class QwenMTStageError(ValueError):
    """The stage draft could not be completed without losing structure."""


def _project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _work_output(path: Path) -> Path:
    return require_work_output(_project_path(path), WORK_ROOT).resolve()


def _default_paths(stage: int) -> dict[str, Path]:
    root = WORK_ROOT / "review" / "local-model" / "aliyun" / f"stage-{stage:03d}"
    stem = f"qwen-mt-plus-stage-{stage:03d}"
    return {
        "output": root / f"{stem}.jsonl",
        "checkpoint": root / f"{stem}.partial.jsonl",
        "raw_output": root / f"{stem}-raw.jsonl",
        "manifest": root / f"{stem}-manifest.json",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--raw-output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--requests-per-minute", type=float, default=DEFAULT_RPM)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--network-attempts", type=int, default=DEFAULT_NETWORK_ATTEMPTS
    )
    parser.add_argument("--format-attempts", type=int, default=2)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def load_env(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise QwenMTStageError(f"cannot read env file {path}: {error}") from error
    values: dict[str, str] = {}
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise QwenMTStageError(f"malformed env line {line_number}: {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if parsed.scheme != "https" or not parsed.netloc:
        raise QwenMTStageError("DASHSCOPE_BASE_URL must be an https URL")
    if not parsed.path.endswith("/compatible-mode/v1"):
        raise QwenMTStageError(
            "DASHSCOPE_BASE_URL must end with /compatible-mode/v1"
        )
    return value.rstrip("/")


def select_stage_rows(
    queue_rows: Sequence[Mapping[str, object]], stage: int
) -> list[Mapping[str, object]]:
    selected = [
        row
        for row in queue_rows
        if int(row["stage_index"]) == stage
        and row.get("review_state") != "locked_reviewed"
    ]
    if not selected:
        raise QwenMTStageError(f"stage {stage:03d} has no unlocked queue rows")
    return selected


def _context_key(row: Mapping[str, object]) -> tuple[object, ...]:
    sections = row.get("sections", [])
    if not isinstance(sections, list):
        sections = []
    return tuple(sections)


def group_stage_rows(
    rows: Sequence[Mapping[str, object]], batch_size: int
) -> list[list[Mapping[str, object]]]:
    if batch_size <= 0:
        raise QwenMTStageError("--batch-size must be positive")
    groups: list[list[Mapping[str, object]]] = []
    current: list[Mapping[str, object]] = []
    current_context: tuple[object, ...] | None = None
    for row in rows:
        if row.get("source_quote_shape") == "control_or_punctuation":
            if current:
                groups.append(current)
                current = []
                current_context = None
            continue
        context = _context_key(row)
        if current and (context != current_context or len(current) >= batch_size):
            groups.append(current)
            current = []
        if not current:
            current_context = context
        current.append(row)
    if current:
        groups.append(current)
    return groups


def segment_id(row: Mapping[str, object]) -> str:
    return f"{int(row['stage_index'])}:{int(row['unique_index'])}"


def build_segment_content(rows: Sequence[Mapping[str, object]]) -> str:
    return "\n".join(
        f'<srwz-seg id="{segment_id(row)}">\n{row["source_text"]}\n</srwz-seg>'
        for row in rows
    )


def parse_segment_response(
    text: str, rows: Sequence[Mapping[str, object]]
) -> dict[str, str]:
    matches = _SEGMENT_PATTERN.findall(text)
    expected = [segment_id(row) for row in rows]
    actual = [item[0] for item in matches]
    if actual != expected:
        raise QwenMTStageError(
            f"segment IDs changed: expected {expected!r}, received {actual!r}"
        )
    return dict(matches)


def _source_spans(text: str, needle: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return spans
        spans.append((index, index + len(needle)))
        start = index + 1


def shadowed_glossary_term_ids(row: Mapping[str, object]) -> set[str]:
    """Return glossary IDs whose every source match is contextually shadowed.

    The queue deliberately uses substring matching.  For example, ``ターン``
    is found inside ``ティターンズ`` even though the dialogue means the
    organization, not a gameplay turn.  A one-character system label can also
    occur inside an ordinary word, such as ``極`` in ``積極的``.  Nested-only
    and one-character word-internal matches must not be sent to Qwen as
    competing terminology.  They are recorded as explicit review exceptions
    so the existing fail-closed importer remains authoritative.
    """

    source_text = str(row["source_text"])
    raw_terms = row.get("glossary_terms", [])
    if not isinstance(raw_terms, list):
        raise QwenMTStageError("queue glossary_terms must be an array")
    matches: dict[str, list[tuple[int, int]]] = {}
    for term in raw_terms:
        if not isinstance(term, Mapping):
            raise QwenMTStageError("queue glossary_terms contains a non-object")
        term_id = term.get("id")
        sources = term.get("source_terms", [])
        if not isinstance(term_id, str) or not isinstance(sources, list):
            raise QwenMTStageError("queue glossary term is malformed")
        term_matches: list[tuple[int, int]] = []
        for source in sources:
            if not isinstance(source, str) or not source:
                continue
            term_matches.extend(_source_spans(source_text, source))
        if term_matches:
            matches[term_id] = sorted(set(term_matches))

    shadowed: set[str] = set()
    for term_id, term_spans in matches.items():
        other_spans = [
            span
            for other_id, spans in matches.items()
            if other_id != term_id
            for span in spans
        ]
        def is_shadowed(start: int, end: int) -> bool:
            nested = any(
                outer_start <= start
                and end <= outer_end
                and outer_end - outer_start > end - start
                for outer_start, outer_end in other_spans
            )
            if nested:
                return True
            if end - start != 1:
                return False
            left = source_text[start - 1] if start else ""
            right = source_text[end] if end < len(source_text) else ""
            return bool(
                (left and _JAPANESE_LEXICAL_CHAR.fullmatch(left))
                or (right and _JAPANESE_LEXICAL_CHAR.fullmatch(right))
            )

        if all(is_shadowed(start, end) for start, end in term_spans):
            shadowed.add(term_id)
    return shadowed


def relevant_terms(rows: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        source_text = str(row["source_text"])
        shadowed = shadowed_glossary_term_ids(row)
        raw_terms = row.get("glossary_terms", [])
        if not isinstance(raw_terms, list):
            raise QwenMTStageError("queue glossary_terms must be an array")
        for term in raw_terms:
            if not isinstance(term, Mapping):
                raise QwenMTStageError("queue glossary_terms contains a non-object")
            target = term.get("translation")
            term_id = term.get("id")
            sources = term.get("source_terms", [])
            if (
                not isinstance(term_id, str)
                or not isinstance(target, str)
                or not isinstance(sources, list)
            ):
                raise QwenMTStageError("queue glossary term is malformed")
            if term_id in shadowed:
                continue
            for source in sources:
                if not isinstance(source, str) or source not in source_text:
                    continue
                pair = (source, target)
                if pair not in seen:
                    seen.add(pair)
                    result.append({"source": source, "target": target})
        structural = row.get("structural_tokens", [])
        if not isinstance(structural, list):
            raise QwenMTStageError("queue structural_tokens must be an array")
        for token in structural:
            if not isinstance(token, str):
                raise QwenMTStageError("queue structural token must be a string")
            pair = (token, token)
            if pair not in seen:
                seen.add(pair)
                result.append({"source": token, "target": token})
    return result


def normalize_translation(row: Mapping[str, object], text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    value = re.sub(r"\n[ \u3000\t]*", "", value)
    value = value.replace("「", "“").replace("」", "”")
    value = value.replace("『", "‘").replace("』", "’")
    value = _ASCII_QUOTES.sub(lambda match: f"“{match.group(1)}”", value)
    value = value.replace("...", "……")
    value = re.sub(r"(?<!…)…(?!…)", "……", value)
    value = _PUNCT_SPACE.sub(r"\1", value)
    value = _PUNCT_TRAILING_SPACE.sub(r"\1", value)
    value = _CLOSE_SPACE.sub(r"\1", value)
    value = _OPEN_SPACE.sub(r"\1", value)
    value = _CJK_SPACE.sub("", value)
    value = _CJK_PUNCT_SPACE.sub("", value)
    value = _LATIN_CJK_SPACE.sub("", value)
    value = _DUPLICATE_SPACE.sub(" ", value).strip(" \t\n\u3000")
    if row.get("source_quote_shape") == "dialogue_quoted":
        value = value.replace("\u3000", "")
    for source, target in _TARGET_SIMPLIFICATIONS.items():
        value = value.replace(source, target)
    if row.get("source_quote_shape") == "dialogue_quoted" and value:
        if not value.startswith(("“", "‘")):
            value = "“" + value
        if not value.endswith(("”", "’")):
            value = value + "”"
    return value


def candidate_for_row(
    row: Mapping[str, object], translation: str
) -> dict[str, object]:
    refs: list[str] = []
    exceptions: list[str] = []
    shadowed = shadowed_glossary_term_ids(row)
    raw_terms = row.get("glossary_terms", [])
    if isinstance(raw_terms, list):
        for term in raw_terms:
            if not isinstance(term, Mapping):
                continue
            term_id = term.get("id")
            canonical = term.get("translation")
            if (
                isinstance(term_id, str)
                and term_id not in shadowed
                and isinstance(canonical, str)
                and canonical
                and canonical in translation
            ):
                refs.append(term_id)
            if (
                isinstance(term_id, str)
                and term_id in shadowed
                and bool(term.get("enforce"))
            ):
                exceptions.append(term_id)
    conflicts = row.get("glossary_conflicts", [])
    notes = ""
    if isinstance(conflicts, list) and conflicts:
        notes = "需人工确认：输入队列存在词表冲突"
    if exceptions:
        nested_note = "嵌套词表子串自动例外：" + ", ".join(sorted(set(exceptions)))
        notes = f"{notes}；{nested_note}" if notes else nested_note
    return {
        "stage_index": int(row["stage_index"]),
        "unique_index": int(row["unique_index"]),
        "source_text_sha256": str(row["source_text_sha256"]),
        "translation": translation,
        "translation_action": "translate",
        "glossary_refs": sorted(set(refs)),
        "glossary_exceptions": sorted(set(exceptions)),
        "notes": notes,
    }


def preserved_candidate(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "stage_index": int(row["stage_index"]),
        "unique_index": int(row["unique_index"]),
        "source_text_sha256": str(row["source_text_sha256"]),
        "translation": str(row["source_text"]),
        "translation_action": "preserve",
        "glossary_refs": [],
        "glossary_exceptions": [],
        "notes": "纯标点或控制项，机器流程原样保留",
    }


class RateLimiter:
    def __init__(self, requests_per_minute: float) -> None:
        if requests_per_minute <= 0:
            raise QwenMTStageError("--requests-per-minute must be positive")
        self._interval = 60.0 / requests_per_minute
        self._lock = threading.Lock()
        self._next_start = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_start - now)
            self._next_start = max(now, self._next_start) + self._interval
        if wait:
            time.sleep(wait)


@dataclass(frozen=True)
class APICall:
    text: str
    record: dict[str, object]


class QwenMTClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        domain: str,
        timeout: float,
        network_attempts: int,
        limiter: RateLimiter,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        if not api_key:
            raise QwenMTStageError("DASHSCOPE_API_KEY is missing or empty")
        if network_attempts <= 0:
            raise QwenMTStageError("--network-attempts must be positive")
        self.api_key = api_key
        self.base_url = validate_base_url(base_url)
        self.model = model
        self.domain = domain
        self.timeout = timeout
        self.network_attempts = network_attempts
        self.limiter = limiter
        self.opener = opener
        self._stats_lock = threading.Lock()
        self._request_count = 0
        self._network_retry_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._request_seconds = 0.0

    def stats(self) -> dict[str, object]:
        with self._stats_lock:
            return {
                "request_count": self._request_count,
                "network_retry_count": self._network_retry_count,
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "request_seconds": round(self._request_seconds, 6),
            }

    def translate(self, rows: Sequence[Mapping[str, object]]) -> APICall:
        terms = relevant_terms(rows)
        options: dict[str, object] = {
            "source_lang": "Japanese",
            "target_lang": "Chinese",
            "domains": self.domain,
        }
        if terms:
            options["terms"] = terms
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": build_segment_content(rows)}],
            "translation_options": options,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(1, self.network_attempts + 1):
            self.limiter.acquire()
            request = Request(
                self.base_url + "/chat/completions",
                data=body,
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            started = time.perf_counter()
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    document = json.loads(response.read().decode("utf-8"))
                elapsed = time.perf_counter() - started
                choices = document.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise QwenMTStageError("Qwen-MT response has no choices")
                choice = choices[0]
                if not isinstance(choice, Mapping):
                    raise QwenMTStageError("Qwen-MT response choice is malformed")
                message = choice.get("message")
                if not isinstance(message, Mapping):
                    raise QwenMTStageError("Qwen-MT response has no message")
                text = message.get("content")
                if not isinstance(text, str) or not text.strip():
                    raise QwenMTStageError("Qwen-MT response content is empty")
                usage = document.get("usage", {})
                if not isinstance(usage, Mapping):
                    usage = {}
                prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                with self._stats_lock:
                    self._request_count += 1
                    self._prompt_tokens += prompt_tokens
                    self._completion_tokens += completion_tokens
                    self._request_seconds += elapsed
                record = {
                    "ids": [segment_id(row) for row in rows],
                    "attempt": attempt,
                    "elapsed_seconds": round(elapsed, 6),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "finish_reason": choice.get("finish_reason"),
                    "model": document.get("model", self.model),
                    "response_text": text,
                }
                return APICall(text=text, record=record)
            except HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                last_error = QwenMTStageError(
                    f"Qwen-MT HTTP {error.code}: {detail[:500]}"
                )
                retryable = error.code in {408, 429, 500, 502, 503, 504}
                retry_after = error.headers.get("Retry-After") if error.headers else None
                if not retryable or attempt >= self.network_attempts:
                    break
                try:
                    delay = float(retry_after) if retry_after else float(2 ** (attempt - 1))
                except ValueError:
                    delay = float(2 ** (attempt - 1))
            except (OSError, URLError, json.JSONDecodeError) as error:
                last_error = error
                if attempt >= self.network_attempts:
                    break
                delay = float(2 ** (attempt - 1))
            with self._stats_lock:
                self._network_retry_count += 1
            time.sleep(min(delay, 30.0))
        raise QwenMTStageError(f"Qwen-MT request failed: {last_error}")


class GroupTranslator:
    def __init__(
        self,
        client: QwenMTClient,
        format_attempts: int,
        record_sink: Callable[[Mapping[str, object]], None] | None = None,
    ) -> None:
        if format_attempts <= 0:
            raise QwenMTStageError("--format-attempts must be positive")
        self.client = client
        self.format_attempts = format_attempts
        self.record_sink = record_sink
        self._split_lock = threading.Lock()
        self._split_count = 0

    def _keep_record(
        self,
        records: list[dict[str, object]],
        record: dict[str, object],
    ) -> None:
        records.append(record)
        if self.record_sink is not None:
            self.record_sink(record)

    @property
    def split_count(self) -> int:
        with self._split_lock:
            return self._split_count

    def _split(self, rows: Sequence[Mapping[str, object]]) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
        with self._split_lock:
            self._split_count += 1
        middle = max(1, len(rows) // 2)
        return list(rows[:middle]), list(rows[middle:])

    def translate(
        self, rows: Sequence[Mapping[str, object]]
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        records: list[dict[str, object]] = []
        last_error: Exception | None = None
        for format_attempt in range(1, self.format_attempts + 1):
            call = self.client.translate(rows)
            record = dict(call.record)
            record["format_attempt"] = format_attempt
            try:
                segments = parse_segment_response(call.text, rows)
            except QwenMTStageError as error:
                record["format_error"] = str(error)
                self._keep_record(records, record)
                last_error = error
                continue

            valid: list[dict[str, object]] = []
            invalid_rows: list[Mapping[str, object]] = []
            validation_errors: dict[str, str] = {}
            for row in rows:
                key = segment_id(row)
                candidate = candidate_for_row(
                    row, normalize_translation(row, segments[key])
                )
                try:
                    valid.append(_validate_translation(row, candidate))
                except TranslationReviewError as error:
                    invalid_rows.append(row)
                    validation_errors[key] = str(error)
                    last_error = error
            if validation_errors:
                record["validation_errors"] = validation_errors
            self._keep_record(records, record)
            if not invalid_rows:
                return valid, records
            if len(rows) > 1:
                recovered, child_records = self.translate(invalid_rows)
                return valid + recovered, records + child_records

        if len(rows) > 1:
            left, right = self._split(rows)
            left_rows, left_records = self.translate(left)
            right_rows, right_records = self.translate(right)
            return left_rows + right_rows, records + left_records + right_records
        raise QwenMTStageError(
            f"stage row {segment_id(rows[0])} failed format/validation retries: {last_error}"
        )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise QwenMTStageError(
                f"invalid checkpoint JSONL at {path}:{line_number}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise QwenMTStageError(f"checkpoint row is not an object: {path}:{line_number}")
        rows.append(value)
    return rows


def _append_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        handle.flush()


class JSONLRecorder:
    """Append complete JSONL records safely from concurrent workers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, record: Mapping[str, object]) -> None:
        value = dict(record)
        value["record_schema_version"] = 1
        with self._lock:
            _append_jsonl(self.path, [value])


def summarize_raw_usage(path: Path) -> dict[str, object]:
    records = _read_jsonl(path)
    prompt_tokens = sum(int(record.get("prompt_tokens", 0) or 0) for record in records)
    completion_tokens = sum(
        int(record.get("completion_tokens", 0) or 0) for record in records
    )
    request_seconds = sum(
        float(record.get("elapsed_seconds", 0.0) or 0.0) for record in records
    )
    network_retry_count = sum(
        max(0, int(record.get("attempt", 1) or 1) - 1) for record in records
    )
    return {
        "request_count": len(records),
        "network_retry_count": network_retry_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "request_seconds": round(request_seconds, 6),
        "total_tokens": prompt_tokens + completion_tokens,
        "format_error_record_count": sum(
            "format_error" in record for record in records
        ),
        "validation_error_record_count": sum(
            "validation_errors" in record for record in records
        ),
        "accounting_complete": bool(records)
        and all(record.get("record_schema_version") == 1 for record in records),
    }


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _resume_rows(
    checkpoint: Path,
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
) -> dict[tuple[int, int], dict[str, object]]:
    result: dict[tuple[int, int], dict[str, object]] = {}
    for candidate in _read_jsonl(checkpoint):
        try:
            key = (int(candidate["stage_index"]), int(candidate["unique_index"]))
        except (KeyError, TypeError, ValueError) as error:
            raise QwenMTStageError("checkpoint row has malformed stable ID") from error
        row = queue_by_key.get(key)
        if row is None:
            raise QwenMTStageError(f"checkpoint row is not in selected stage: {key!r}")
        if key in result:
            raise QwenMTStageError(f"checkpoint contains duplicate row: {key!r}")
        normalized = dict(candidate)
        if normalized.get("translation_action", "translate") == "translate":
            translation = normalized.get("translation")
            if isinstance(translation, str):
                normalized["translation"] = normalize_translation(row, translation)
        try:
            result[key] = _validate_translation(row, normalized)
        except TranslationReviewError as error:
            raise QwenMTStageError(f"checkpoint row failed validation: {error}") from error
    return result


def main() -> int:
    args = parse_args()
    if args.stage < 0:
        raise QwenMTStageError("--stage must be non-negative")
    if args.batch_size <= 0 or args.batch_size > 32:
        raise QwenMTStageError("--batch-size must be between 1 and 32")
    if args.workers <= 0 or args.workers > 16:
        raise QwenMTStageError("--workers must be between 1 and 16")

    defaults = _default_paths(args.stage)
    output = _work_output(args.output or defaults["output"])
    checkpoint = _work_output(args.checkpoint or defaults["checkpoint"])
    raw_output = _work_output(args.raw_output or defaults["raw_output"])
    manifest = _work_output(args.manifest or defaults["manifest"])
    if output.exists() and not args.resume:
        raise QwenMTStageError(f"output exists; use --resume: {output}")
    if checkpoint.exists() and not args.resume:
        raise QwenMTStageError(f"checkpoint exists; use --resume: {checkpoint}")

    queue_path = _project_path(args.input).resolve()
    queue_rows = load_queue(queue_path)
    stage_rows = select_stage_rows(queue_rows, args.stage)
    queue_by_key = {
        (int(row["stage_index"]), int(row["unique_index"])): row
        for row in stage_rows
    }
    completed = _resume_rows(checkpoint, queue_by_key) if args.resume else {}
    if args.resume and output.exists():
        for key, candidate in _resume_rows(output, queue_by_key).items():
            completed.setdefault(key, candidate)

    preserve_rows = [
        row
        for row in stage_rows
        if row.get("source_quote_shape") == "control_or_punctuation"
        and (int(row["stage_index"]), int(row["unique_index"])) not in completed
    ]
    preserved = []
    for row in preserve_rows:
        preserved.append(_validate_translation(row, preserved_candidate(row)))
    if preserved:
        _append_jsonl(checkpoint, preserved)
        for candidate in preserved:
            completed[(candidate["stage_index"], candidate["unique_index"])] = candidate

    pending_rows = [
        row
        for row in stage_rows
        if (int(row["stage_index"]), int(row["unique_index"])) not in completed
        and row.get("source_quote_shape") != "control_or_punctuation"
    ]
    groups = group_stage_rows(pending_rows, args.batch_size)
    stage_groups = group_stage_rows(
        [
            row
            for row in stage_rows
            if row.get("source_quote_shape") != "control_or_punctuation"
        ],
        args.batch_size,
    )

    env = load_env(_project_path(args.env_file).resolve())
    client = QwenMTClient(
        api_key=env.get("DASHSCOPE_API_KEY", ""),
        base_url=env.get("DASHSCOPE_BASE_URL", ""),
        model=args.model,
        domain=args.domain,
        timeout=args.timeout,
        network_attempts=args.network_attempts,
        limiter=RateLimiter(args.requests_per_minute),
    )
    raw_recorder = JSONLRecorder(raw_output)
    translator = GroupTranslator(
        client, args.format_attempts, record_sink=raw_recorder.append
    )
    started = time.perf_counter()

    if groups:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(translator.translate, group): group for group in groups}
            for future in as_completed(futures):
                group = futures[future]
                try:
                    candidates, _raw_records = future.result()
                except Exception as error:
                    for other in futures:
                        other.cancel()
                    raise QwenMTStageError(
                        f"stage group {[segment_id(row) for row in group]} failed: {error}"
                    ) from error
                candidates.sort(key=lambda item: (item["stage_index"], item["unique_index"]))
                _append_jsonl(checkpoint, candidates)
                for candidate in candidates:
                    completed[(candidate["stage_index"], candidate["unique_index"])] = candidate
                stats = client.stats()
                print(
                    f"stage={args.stage:03d} completed={len(completed)}/{len(stage_rows)} "
                    f"requests={stats['request_count']} tokens="
                    f"{stats['prompt_tokens']}+{stats['completion_tokens']}",
                    flush=True,
                )

    required_keys = set(queue_by_key)
    missing = sorted(required_keys - set(completed))
    if missing:
        raise QwenMTStageError(
            f"stage {args.stage:03d} incomplete after run: {len(missing)} missing"
        )
    ordered = [
        completed[(int(row["stage_index"]), int(row["unique_index"]))]
        for row in stage_rows
    ]
    _write_jsonl(output, ordered)
    _, validated_by_key, missing_rows = validate_model_output(
        queue_rows, ordered, allow_partial=True
    )
    stage_missing = [
        row for row in missing_rows if int(row["stage_index"]) == args.stage
    ]
    if stage_missing or len(validated_by_key) != len(stage_rows):
        raise QwenMTStageError(
            f"final importer audit failed for stage {args.stage:03d}"
        )

    wall_seconds = time.perf_counter() - started
    run_stats = client.stats()
    usage = summarize_raw_usage(raw_output)
    prompt_tokens = int(usage["prompt_tokens"])
    completion_tokens = int(usage["completion_tokens"])
    cost = prompt_tokens / 1_000_000 * 1.8 + completion_tokens / 1_000_000 * 5.4
    document = {
        "schema_version": 1,
        "stage_index": args.stage,
        "model": args.model,
        "provider": "Alibaba Cloud Model Studio OpenAI-compatible API",
        "source_queue": str(queue_path.relative_to(PROJECT_ROOT)),
        "source_queue_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
        "row_count": len(stage_rows),
        "preserved_row_count": len(
            [row for row in ordered if row["translation_action"] == "preserve"]
        ),
        "translated_row_count": len(
            [row for row in ordered if row["translation_action"] == "translate"]
        ),
        "initial_group_count": len(stage_groups),
        "run_pending_group_count": len(groups),
        "batch_size": args.batch_size,
        "workers": args.workers,
        "requests_per_minute": args.requests_per_minute,
        "run_split_count": translator.split_count,
        **usage,
        "estimated_cost_cny": round(cost, 6),
        "run_wall_seconds": round(wall_seconds, 6),
        "run_stats": run_stats,
        "output": str(output.relative_to(PROJECT_ROOT)),
        "checkpoint": str(checkpoint.relative_to(PROJECT_ROOT)),
        "raw_output": str(raw_output.relative_to(PROJECT_ROOT)),
        "strict_validation": {
            "stage_model_rows": len(validated_by_key),
            "stage_missing_rows": len(stage_missing),
            "passed": not stage_missing and len(validated_by_key) == len(stage_rows),
        },
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Qwen-MT stage complete: stage={args.stage:03d} rows={len(stage_rows)} "
        f"recorded_requests={usage['request_count']} cost_cny={cost:.4f} "
        f"wall={wall_seconds:.2f}s",
        flush=True,
    )
    print(f"model output: {output}")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (QwenMTStageError, TranslationReviewError) as error:
        print(f"Qwen-MT stage error: {error}", file=sys.stderr)
        raise SystemExit(1)
