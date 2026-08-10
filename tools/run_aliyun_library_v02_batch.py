#!/usr/bin/env python3
"""Run one strict, review-only LIBRARY translation batch on DashScope.

The default model is Alibaba Cloud's ``deepseek-v4-flash-0731``.  Exact source IDs and
hashes are validated before the request; returned IDs, JSON shape, Japanese
kana, manual line breaks, punctuation, and approved glossary terms are checked
before any row enters ``validated.jsonl``.  All billable artifacts stay below
ignored ``work/`` and are never promoted into ``corpus/zh`` by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

try:
    from srwz.diagnostics import require_work_output
    from srwz.library import LibraryScopeError
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.library import LibraryScopeError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_QUEUE = WORK_ROOT / "review/aliyun/library-v0.2/source-queue.jsonl"
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_MODEL = "deepseek-v4-flash-0731"
KANA_PATTERN = re.compile(
    r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]"
)
MODEL_RESIDUE = re.compile(r"```|(?:\}\s*\]|\]\s*\})")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class APICall:
    response_text: str
    response_model: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    elapsed_seconds: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--domain", choices=("robot", "character", "glossary"))
    parser.add_argument("--phase", choices=("metadata", "body"))
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="select rows referenced by this ZKAN field tag; repeatable",
    )
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def work_output(path: Path) -> Path:
    return require_work_output(project_path(path), WORK_ROOT).resolve()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LibraryScopeError(
                f"invalid JSONL at {path}:{line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise LibraryScopeError(
                f"JSONL row is not an object at {path}:{line_number}"
            )
        rows.append(value)
    return rows


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise LibraryScopeError(f"malformed env line {line_number}: {path}")
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def validate_base_url(value: str) -> str:
    result = value.rstrip("/")
    parsed = urlsplit(result)
    if parsed.scheme != "https" or not parsed.netloc:
        raise LibraryScopeError("DASHSCOPE_BASE_URL must be an https URL")
    if not parsed.path.endswith("/compatible-mode/v1"):
        raise LibraryScopeError(
            "DASHSCOPE_BASE_URL must end with /compatible-mode/v1"
        )
    return result


def validate_queue(rows: Sequence[Mapping[str, object]]) -> None:
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, 1):
        if row.get("schema_version") != 1:
            raise LibraryScopeError(f"queue row {row_number} has unsupported schema")
        row_id = row.get("id")
        source = row.get("source_text")
        model_source = row.get("model_source_text")
        source_hash = row.get("source_text_sha256")
        references = row.get("references")
        terms = row.get("glossary_terms")
        if not isinstance(row_id, str) or not row_id.startswith("library-text/"):
            raise LibraryScopeError(f"queue row {row_number} has malformed id")
        if row_id in seen_ids:
            raise LibraryScopeError(f"duplicate queue id: {row_id}")
        seen_ids.add(row_id)
        if not isinstance(source, str) or not source.strip():
            raise LibraryScopeError(f"queue row {row_number} has empty source")
        if not isinstance(model_source, str) or "\n" in model_source or "\r" in model_source:
            raise LibraryScopeError(
                f"queue row {row_number} model source contains a line break"
            )
        if (
            not isinstance(source_hash, str)
            or not SHA256_PATTERN.fullmatch(source_hash)
            or sha256_text(source) != source_hash
        ):
            raise LibraryScopeError(
                f"queue row {row_number} source hash does not match"
            )
        if not isinstance(references, list) or not references:
            raise LibraryScopeError(f"queue row {row_number} has no references")
        if not isinstance(terms, list):
            raise LibraryScopeError(
                f"queue row {row_number} glossary_terms must be an array"
            )


def select_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    domain: str | None,
    tags: Sequence[str] = (),
    phase: str | None = None,
    offset: int,
    limit: int,
) -> list[Mapping[str, object]]:
    if offset < 0 or limit <= 0:
        raise LibraryScopeError("--offset must be non-negative and --limit positive")
    filtered = list(rows)
    if domain is not None:
        filtered = [
            row
            for row in filtered
            if any(
                isinstance(reference, Mapping)
                and reference.get("domain") == domain
                for reference in row["references"]
            )
        ]
    if tags:
        requested = set(tags)
        filtered = [
            row
            for row in filtered
            if any(
                isinstance(reference, Mapping)
                and reference.get("tag") in requested
                for reference in row["references"]
            )
        ]
    if phase is not None:
        metadata_tags = {
            "ACTR",
            "CHFN",
            "CHNN",
            "HEIT",
            "PLTN",
            "PRDC",
            "RBTN",
            "SRCE",
            "WEIT",
            "WORD",
        }
        expected_metadata = phase == "metadata"
        filtered = [
            row
            for row in filtered
            if any(
                isinstance(reference, Mapping)
                and reference.get("tag") in metadata_tags
                for reference in row["references"]
            )
            is expected_metadata
        ]
    selected = filtered[offset : offset + limit]
    if not selected:
        raise LibraryScopeError("the requested queue slice is empty")
    return selected


def prompt_terms(row: Mapping[str, object]) -> list[dict[str, object]]:
    source = str(row["model_source_text"]).strip("　 ")
    selected: list[dict[str, object]] = []
    for raw in row.get("glossary_terms", []):
        if not isinstance(raw, Mapping):
            continue
        matched = raw.get("matched_source_terms", [])
        exact = isinstance(matched, list) and any(
            isinstance(item, str) and item == source for item in matched
        )
        enforce = raw.get("enforce") is True
        researched = raw.get("status") in {"approved", "researched"}
        if enforce or researched or exact:
            selected.append(
                {
                    "id": raw.get("id"),
                    "source": matched,
                    "target": raw.get("translation"),
                    "required": enforce,
                }
            )
    return selected


def build_messages(rows: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    segments = [
        {
            "id": row["id"],
            "jp": row["model_source_text"],
            "terms": prompt_terms(row),
        }
        for row in rows
    ]
    system = """你是《超级机器人大战Z》图鉴与百科文本的日中本地化译者。将日文翻译成自然、准确、简洁的简体中文。

硬性要求：
1. 只返回一个有效 JSON 对象，格式严格为 {"translations":[{"id":"library-text/...","text":"中文译文"}]}，不得使用 Markdown 或解释。
2. 每个输入 ID 必须恰好返回一次，顺序完全一致；每项只允许 id 和 text。
3. 译文不得含手工换行、日文假名、日式直角引号「」或书名号『』；作品名使用中文书名号《》。
4. 不增删事实，不把设定说明改写成宣传文案；全角数字、英文字母和单位可按简体中文习惯转为半角。
5. terms 中 required=true 的译名必须采用；required=false 仅在当前百科语境合适时采用，不要机械扩写。
6. 人名、机体名、组织名与作品名优先沿用项目术语；音乐曲名不在本批输入中，禁止臆造音乐条目。
7. 原文中的换行只是游戏硬换行，输出必须是一段连续文本；保留原有段落含义。"""
    user = (
        "请翻译以下 JSON 数组。只输出规定的 JSON 对象：\n"
        + json.dumps(segments, ensure_ascii=False, separators=(",", ":"))
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def request_payload(
    model: str, messages: Sequence[Mapping[str, str]], max_tokens: int
) -> dict[str, object]:
    return {
        "model": model,
        "messages": list(messages),
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "enable_thinking": False,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


def call_api(
    *, api_key: str, base_url: str, payload: Mapping[str, object], timeout: float
) -> APICall:
    request = Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LibraryScopeError(f"DashScope HTTP {exc.code}: {detail[:1000]}") from exc
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise LibraryScopeError(f"DashScope request failed: {exc}") from exc
    elapsed = time.perf_counter() - started
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LibraryScopeError("DashScope response has no choices")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise LibraryScopeError("DashScope choice is malformed")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content:
        raise LibraryScopeError("DashScope response content is empty")
    usage = document.get("usage", {})
    if not isinstance(usage, Mapping):
        usage = {}
    prompt_details = usage.get("prompt_tokens_details", {})
    if not isinstance(prompt_details, Mapping):
        prompt_details = {}
    return APICall(
        response_text=content,
        response_model=str(document.get("model", payload["model"])),
        finish_reason=(
            str(choice["finish_reason"])
            if choice.get("finish_reason") is not None
            else None
        ),
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        cached_tokens=int(prompt_details.get("cached_tokens", 0) or 0),
        elapsed_seconds=elapsed,
    )


def parse_response(
    text: str, rows: Sequence[Mapping[str, object]]
) -> tuple[list[tuple[Mapping[str, object], str]], dict[str, object]]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], {"json_valid": False, "error": str(exc)}
    translations = document.get("translations") if isinstance(document, Mapping) else None
    if not isinstance(translations, list):
        return [], {"json_valid": True, "error": "translations is not an array"}
    expected = [str(row["id"]) for row in rows]
    actual: list[str] = []
    values: list[str] = []
    malformed = 0
    for item in translations:
        if not isinstance(item, Mapping) or set(item) != {"id", "text"}:
            malformed += 1
            continue
        item_id = item.get("id")
        value = item.get("text")
        if not isinstance(item_id, str) or not isinstance(value, str):
            malformed += 1
            continue
        actual.append(item_id)
        values.append(value)
    audit = {
        "json_valid": True,
        "translation_item_count": len(translations),
        "well_formed_item_count": len(actual),
        "malformed_item_count": malformed,
        "exact_id_order": actual == expected,
        "missing_ids": sorted(set(expected) - set(actual)),
        "unexpected_ids": sorted(set(actual) - set(expected)),
        "duplicate_ids": sorted(
            item_id for item_id in set(actual) if actual.count(item_id) > 1
        ),
    }
    if actual != expected:
        audit["error"] = "returned IDs do not exactly match the input order"
        return [], audit
    return list(zip(rows, values)), audit


def validate_translation(
    row: Mapping[str, object], text: str, *, model: str = DEFAULT_MODEL
) -> dict[str, object]:
    context = str(row["id"])
    translation = text.strip()
    if not translation:
        raise LibraryScopeError(f"{context}: translation is empty")
    if "\n" in translation or "\r" in translation:
        raise LibraryScopeError(f"{context}: translation contains manual line breaks")
    if KANA_PATTERN.search(translation):
        raise LibraryScopeError(f"{context}: translation contains Japanese kana")
    if any(mark in translation for mark in ("「", "」", "『", "』")):
        raise LibraryScopeError(f"{context}: translation contains Japanese brackets")
    if "..." in translation:
        raise LibraryScopeError(f"{context}: translation uses three-dot ellipsis")
    if MODEL_RESIDUE.search(translation):
        raise LibraryScopeError(f"{context}: translation contains model residue")

    glossary_refs: list[str] = []
    for raw in row.get("glossary_terms", []):
        if not isinstance(raw, Mapping):
            continue
        target = raw.get("translation")
        term_id = raw.get("id")
        if isinstance(target, str) and target and target in translation:
            if isinstance(term_id, str):
                glossary_refs.append(term_id)
        elif raw.get("enforce") is True:
            raise LibraryScopeError(
                f"{context}: required glossary target is missing: {target!r}"
            )
    return {
        "schema_version": 1,
        "id": row["id"],
        "source_text_sha256": row["source_text_sha256"],
        "translation": translation,
        "editorial_status": "machine_draft",
        "translation_action": "translate",
        "glossary_refs": sorted(set(glossary_refs)),
        "model": "aliyun:" + model,
        "notes": "阿里云 DeepSeek 初译；尚未晋升正式语料。",
    }


def default_output_dir(
    *,
    model: str,
    domain: str | None,
    phase: str | None,
    tags: Sequence[str],
    offset: int,
    count: int,
    attempt: int,
) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")
    tag_scope = "-".join(sorted(tags)) if tags else ""
    scope = "-".join(
        item for item in (domain or "all", phase or "", tag_scope) if item
    )
    return (
        WORK_ROOT
        / "review/aliyun/library-v0.2"
        / safe_model
        / "batches"
        / f"{scope}-{offset:04d}-{count:04d}"
        / f"attempt-{attempt}"
    )


def main() -> int:
    args = parse_args()
    if args.max_tokens <= 0 or args.timeout <= 0 or args.attempt <= 0:
        raise LibraryScopeError("token, timeout, and attempt values must be positive")
    queue_path = project_path(args.queue).resolve()
    queue = read_jsonl(queue_path)
    validate_queue(queue)
    selected = select_rows(
        queue,
        domain=args.domain,
        tags=args.tag,
        phase=args.phase,
        offset=args.offset,
        limit=args.limit,
    )
    output_dir = work_output(
        args.output_dir
        or default_output_dir(
            model=args.model,
            domain=args.domain,
            phase=args.phase,
            tags=args.tag,
            offset=args.offset,
            count=len(selected),
            attempt=args.attempt,
        )
    )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite a completed/billable attempt: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    env = load_env(project_path(args.env_file).resolve())
    api_key = env.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise LibraryScopeError("DASHSCOPE_API_KEY is missing or empty")
    base_url = validate_base_url(env.get("DASHSCOPE_BASE_URL", ""))
    messages = build_messages(selected)
    payload = request_payload(args.model, messages, args.max_tokens)
    write_json(
        output_dir / "request.json",
        {
            "schema_version": 1,
            "model": args.model,
            "source_queue": str(queue_path.relative_to(PROJECT_ROOT)),
            "source_queue_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
            "selected_ids": [row["id"] for row in selected],
            "messages": messages,
            "temperature": payload["temperature"],
            "max_tokens": args.max_tokens,
            "enable_thinking": False,
        },
    )
    call = call_api(
        api_key=api_key,
        base_url=base_url,
        payload=payload,
        timeout=args.timeout,
    )
    write_json(output_dir / "response.json", {"response_text": call.response_text})
    paired, format_audit = parse_response(call.response_text, selected)
    parsed: list[dict[str, object]] = []
    validated: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    for row, translation in paired:
        candidate = {
            "id": row["id"],
            "source_text_sha256": row["source_text_sha256"],
            "translation": translation,
        }
        parsed.append(candidate)
        try:
            validated.append(validate_translation(row, translation, model=args.model))
        except LibraryScopeError as exc:
            errors[str(row["id"])] = str(exc)
    write_jsonl(output_dir / "parsed.jsonl", parsed)
    write_jsonl(output_dir / "validated.jsonl", validated)
    strict_passed = bool(format_audit.get("exact_id_order")) and not errors and (
        len(validated) == len(selected)
    )
    manifest = {
        "schema_version": 1,
        "kind": "aliyun_library_v0.2_translation_batch",
        "requested_model": args.model,
        "response_model": call.response_model,
        "domain": args.domain,
        "phase": args.phase,
        "tags": args.tag,
        "offset": args.offset,
        "selected_count": len(selected),
        "sound_track_titles_included": False,
        "run": {
            "finish_reason": call.finish_reason,
            "prompt_tokens": call.prompt_tokens,
            "completion_tokens": call.completion_tokens,
            "cached_tokens": call.cached_tokens,
            "elapsed_seconds": round(call.elapsed_seconds, 6),
        },
        "format_audit": format_audit,
        "validation": {
            "parsed_count": len(parsed),
            "passed_count": len(validated),
            "failed_count": len(errors),
            "errors": errors,
            "strict_passed": strict_passed,
        },
        "artifacts": {
            "request": str((output_dir / "request.json").relative_to(PROJECT_ROOT)),
            "raw_response": str(
                (output_dir / "response.json").relative_to(PROJECT_ROOT)
            ),
            "parsed": str((output_dir / "parsed.jsonl").relative_to(PROJECT_ROOT)),
            "validated": str(
                (output_dir / "validated.jsonl").relative_to(PROJECT_ROOT)
            ),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    print(
        f"model={args.model} tokens={call.prompt_tokens}+{call.completion_tokens} "
        f"elapsed={call.elapsed_seconds:.3f}s validated={len(validated)}/"
        f"{len(selected)} strict={strict_passed}"
    )
    print((output_dir / "manifest.json").relative_to(PROJECT_ROOT))
    return 0 if strict_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
