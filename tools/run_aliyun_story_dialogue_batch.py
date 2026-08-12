#!/usr/bin/env python3
"""Run strict, context-rich story-dialogue translation batches on DashScope.

Every queue row must identify the speaker, the speaker's work, and adjacent
same-scene lines.  The command fails before making a billable request if any
of that context is absent.  Results stay below ``work/`` as machine drafts;
this command never writes ``corpus/zh``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

try:
    import run_aliyun_library_v02_batch as transport
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools import run_aliyun_library_v02_batch as transport

try:
    from srwz.diagnostics import require_work_output
    from srwz.library import LibraryScopeError
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.library import LibraryScopeError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_MODEL = "deepseek-v4-flash-0731"
KANA_PATTERN = re.compile(
    r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]"
)
VARIABLE_PATTERN = re.compile(r"\$[A-Za-z]")
STORY_ID_PATTERN = re.compile(
    r"story/(?P<stage>\d{3})/dialogue/\d{2}\.\d{2,3}/\d{4}"
)
SEMANTIC_ROLES = {"speaker", "addressee", "third", "generic"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--max-tokens", type=int, default=16_384)
    parser.add_argument("--timeout", type=float, default=900.0)
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return transport.read_jsonl(path)


def _validate_speaker(value: object, *, context: str) -> None:
    if not isinstance(value, Mapping):
        raise LibraryScopeError(f"{context}: speaker must be an object")
    if set(value) != {"ja", "zh", "identity", "work"}:
        raise LibraryScopeError(
            f"{context}: speaker must contain ja, zh, identity, and work"
        )
    for field in ("ja", "zh", "identity", "work"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise LibraryScopeError(f"{context}: speaker.{field} is empty")
    work = str(value["work"])
    if not (work.startswith("《") and work.endswith("》")):
        raise LibraryScopeError(
            f"{context}: speaker.work must be an explicit Chinese work title"
        )


def _validate_context_item(
    value: object,
    *,
    current_id: str,
    label: str,
    position: int,
) -> None:
    context = f"{current_id}:{label}[{position}]"
    if not isinstance(value, Mapping):
        raise LibraryScopeError(f"{context}: context item must be an object")
    if set(value) != {"id", "speaker", "jp"}:
        raise LibraryScopeError(
            f"{context}: context item must contain id, speaker, and jp"
        )
    item_id = value.get("id")
    jp = value.get("jp")
    if not isinstance(item_id, str) or STORY_ID_PATTERN.fullmatch(item_id) is None:
        raise LibraryScopeError(f"{context}: malformed context id")
    if item_id.split("/")[1] != current_id.split("/")[1]:
        raise LibraryScopeError(f"{context}: context crosses STAGE boundaries")
    if not isinstance(jp, str) or not jp.strip():
        raise LibraryScopeError(f"{context}: context Japanese text is empty")
    _validate_speaker(value.get("speaker"), context=context)


def validate_queue(rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise LibraryScopeError("story translation queue is empty")
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, 1):
        context = f"queue row {row_number}"
        row_id = row.get("id")
        source = row.get("source_text")
        source_hash = row.get("source_text_sha256")
        if not isinstance(row_id, str) or STORY_ID_PATTERN.fullmatch(row_id) is None:
            raise LibraryScopeError(f"{context}: malformed story dialogue id")
        if row_id in seen_ids:
            raise LibraryScopeError(f"duplicate story dialogue id: {row_id}")
        seen_ids.add(row_id)
        if not isinstance(source, str) or not source.strip():
            raise LibraryScopeError(f"{row_id}: source_text is empty")
        if source_hash != sha256_text(source):
            raise LibraryScopeError(f"{row_id}: source hash does not match")
        if row.get("stage_index") != int(row_id.split("/")[1]):
            raise LibraryScopeError(f"{row_id}: stage_index does not match id")
        if not isinstance(row.get("section"), str) or not row["section"]:
            raise LibraryScopeError(f"{row_id}: section is empty")
        _validate_speaker(row.get("speaker"), context=row_id)
        before = row.get("context_before")
        after = row.get("context_after")
        if not isinstance(before, list) or not isinstance(after, list):
            raise LibraryScopeError(
                f"{row_id}: context_before and context_after must be arrays"
            )
        if len(before) > 2 or len(after) > 2:
            raise LibraryScopeError(f"{row_id}: adjacent context exceeds two lines")
        if not before and not after:
            raise LibraryScopeError(
                f"{row_id}: no adjacent context; add an explicit neighboring line"
            )
        for position, item in enumerate(before):
            _validate_context_item(
                item,
                current_id=row_id,
                label="context_before",
                position=position,
            )
        for position, item in enumerate(after):
            _validate_context_item(
                item,
                current_id=row_id,
                label="context_after",
                position=position,
            )
        if not isinstance(row.get("required_terms"), list):
            raise LibraryScopeError(f"{row_id}: required_terms must be an array")


def prompt_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": row["id"],
        "stage_index": row["stage_index"],
        "section": row["section"],
        "speaker": row["speaker"],
        "context_before": row["context_before"],
        "jp": row["source_text"],
        "context_after": row["context_after"],
        "required_terms": row["required_terms"],
    }


def build_messages(rows: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    system = """你是《超级机器人大战Z》的日中本地化译者。每条输入都提供当前说话人的日文名、项目中文名、真实身份、所属作品，以及同一场景的前后文。必须结合这些信息翻译，不能把同名角色、跨作品术语或主人公分支混淆。

规则：
1. 严格保留 $n、$c、$f 等变量；不得解释、扩写或遗漏信息。
2. 保留原文的引号或括号语气。普通「」改为中文双引号“”；（ ）仍用全角括号。省略号统一用……。
3. required_terms 中列出的术语必须使用指定中文；同一日文若绑定多个同译术语，只出现一次中文即可。
4. 日文省略指代且上下文不能唯一确定时，优先使用自然的无代词中文，不擅自补我、你、他或性别。
5. 玩家选择文本必须保留标题、选项1、选项2三行结构；其他对白最多三行，可先输出自然完整句，后续由排版器重排。
6. 地点名、菜单提示等无说话人的文本直接翻译，不添加引号。不得残留平假名或片假名。
7. semantic_roles 只可选 speaker、addressee、third、generic。ambiguous 仅在上下文无法确定省略角色时为 true。referent 用不超过40个汉字说明指代依据；没有指代时写“无指代”。
8. 只输出有效 JSON：{"translations":[{"id":"原ID","text":"完整中文译文","confidence":"high|medium|low","semantic_roles":["speaker|addressee|third|generic"],"ambiguous":false,"referent":"指代依据"}]}。不得输出 Markdown 或额外字段；ID 与顺序必须完全一致。"""
    user = (
        "独立翻译以下 JSON 数组：\n"
        + json.dumps(
            [prompt_row(row) for row in rows],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_response(
    text: str,
    rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], {"json_valid": False, "error": str(exc)}
    translations = document.get("translations") if isinstance(document, Mapping) else None
    if not isinstance(translations, list):
        return [], {"json_valid": True, "error": "translations is not an array"}
    required_fields = {
        "id",
        "text",
        "confidence",
        "semantic_roles",
        "ambiguous",
        "referent",
    }
    parsed: list[dict[str, object]] = []
    malformed = 0
    for item in translations:
        if not isinstance(item, dict) or set(item) != required_fields:
            malformed += 1
            continue
        parsed.append(item)
    expected_ids = [str(row["id"]) for row in rows]
    actual_ids = [str(item.get("id")) for item in parsed]
    audit = {
        "json_valid": True,
        "translation_item_count": len(translations),
        "well_formed_item_count": len(parsed),
        "malformed_item_count": malformed,
        "exact_id_order": actual_ids == expected_ids,
        "missing_ids": sorted(set(expected_ids) - set(actual_ids)),
        "unexpected_ids": sorted(set(actual_ids) - set(expected_ids)),
    }
    if actual_ids != expected_ids:
        audit["error"] = "returned IDs do not exactly match input order"
        return [], audit
    return parsed, audit


def validate_translation(
    row: Mapping[str, object], item: Mapping[str, object]
) -> dict[str, object]:
    row_id = str(row["id"])
    text = item.get("text")
    confidence = item.get("confidence")
    roles = item.get("semantic_roles")
    ambiguous = item.get("ambiguous")
    referent = item.get("referent")
    if not isinstance(text, str) or not text.strip():
        raise LibraryScopeError(f"{row_id}: translation is empty")
    if confidence not in {"high", "medium", "low"}:
        raise LibraryScopeError(f"{row_id}: invalid confidence")
    if (
        not isinstance(roles, list)
        or not roles
        or any(role not in SEMANTIC_ROLES for role in roles)
    ):
        raise LibraryScopeError(f"{row_id}: invalid semantic_roles")
    if not isinstance(ambiguous, bool):
        raise LibraryScopeError(f"{row_id}: ambiguous must be boolean")
    if not isinstance(referent, str) or not referent.strip() or len(referent) > 40:
        raise LibraryScopeError(f"{row_id}: referent must contain at most 40 characters")
    if KANA_PATTERN.search(text):
        raise LibraryScopeError(f"{row_id}: translation contains Japanese kana")
    if "..." in text or any(mark in text for mark in ("「", "」", "『", "』")):
        raise LibraryScopeError(f"{row_id}: translation punctuation is not normalized")
    if len(text.splitlines()) > 3:
        raise LibraryScopeError(f"{row_id}: translation exceeds three runtime rows")
    source_variables = Counter(VARIABLE_PATTERN.findall(str(row["source_text"])))
    target_variables = Counter(VARIABLE_PATTERN.findall(text))
    if source_variables != target_variables:
        raise LibraryScopeError(f"{row_id}: runtime variable set changed")
    for term in row["required_terms"]:
        if not isinstance(term, Mapping):
            raise LibraryScopeError(f"{row_id}: malformed required term")
        target = term.get("translation")
        if not isinstance(target, str) or not target or target not in text:
            raise LibraryScopeError(
                f"{row_id}: required term is missing from translation: {target!r}"
            )
    return {
        "id": row_id,
        "source_text_sha256": row["source_text_sha256"],
        "translation": text,
        "confidence": confidence,
        "semantic_roles": roles,
        "ambiguous": ambiguous,
        "referent": referent,
    }


def _write_json(path: Path, value: object) -> None:
    transport.write_json(path, value)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    transport.write_jsonl(path, rows)


def main() -> int:
    args = parse_args()
    if (
        args.model != DEFAULT_MODEL
        or args.batch_size <= 0
        or args.max_tokens <= 0
        or args.timeout <= 0
    ):
        raise LibraryScopeError(
            "story batches require deepseek-v4-flash-0731 and positive limits"
        )
    queue_path = project_path(args.queue).resolve()
    queue = read_jsonl(queue_path)
    validate_queue(queue)
    output_dir = require_work_output(
        project_path(args.output_dir), WORK_ROOT
    ).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite completed or billable artifacts: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    env = transport.load_env(project_path(args.env_file).resolve())
    api_key = env.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise LibraryScopeError("DASHSCOPE_API_KEY is missing or empty")
    base_url = transport.validate_base_url(env.get("DASHSCOPE_BASE_URL", ""))

    aggregate: list[dict[str, object]] = []
    receipts: list[dict[str, object]] = []
    for batch_index, offset in enumerate(range(0, len(queue), args.batch_size)):
        rows = queue[offset : offset + args.batch_size]
        batch_id = f"batch-{batch_index:04d}"
        batch_dir = output_dir / "batches" / batch_id
        batch_dir.mkdir(parents=True, exist_ok=False)
        messages = build_messages(rows)
        payload = transport.request_payload(args.model, messages, args.max_tokens)
        _write_json(
            batch_dir / "request.json",
            {
                "schema_version": 1,
                "model": args.model,
                "selected_ids": [row["id"] for row in rows],
                "messages": messages,
                "temperature": payload["temperature"],
                "max_tokens": args.max_tokens,
                "enable_thinking": False,
            },
        )
        call = transport.call_api(
            api_key=api_key,
            base_url=base_url,
            payload=payload,
            timeout=args.timeout,
        )
        _write_json(
            batch_dir / "response.json",
            {"response_text": call.response_text},
        )
        parsed, format_audit = parse_response(call.response_text, rows)
        validated: list[dict[str, object]] = []
        errors: dict[str, str] = {}
        for row, item in zip(rows, parsed):
            try:
                validated.append(validate_translation(row, item))
            except LibraryScopeError as exc:
                errors[str(row["id"])] = str(exc)
        strict_passed = (
            bool(format_audit.get("exact_id_order"))
            and not errors
            and len(validated) == len(rows)
        )
        _write_jsonl(batch_dir / "translations.jsonl", validated)
        receipt = {
            "schema_version": 1,
            "batch_id": batch_id,
            "requested_model": args.model,
            "response_model": call.response_model,
            "selected_count": len(rows),
            "format_audit": format_audit,
            "validation": {
                "passed_count": len(validated),
                "failed_count": len(errors),
                "errors": errors,
                "strict_passed": strict_passed,
            },
            "run": {
                "finish_reason": call.finish_reason,
                "prompt_tokens": call.prompt_tokens,
                "completion_tokens": call.completion_tokens,
                "cached_tokens": call.cached_tokens,
                "elapsed_seconds": round(call.elapsed_seconds, 6),
            },
        }
        _write_json(batch_dir / "receipt.json", receipt)
        receipts.append(receipt)
        if not strict_passed:
            _write_json(
                output_dir / "manifest.json",
                {
                    "schema_version": 1,
                    "kind": "context_rich_story_dialogue_machine_draft",
                    "model": args.model,
                    "source_queue_sha256": hashlib.sha256(
                        queue_path.read_bytes()
                    ).hexdigest(),
                    "candidate_count": len(queue),
                    "completed_batch_count": len(receipts),
                    "strict_passed": False,
                },
            )
            return 2
        aggregate.extend(validated)

    _write_jsonl(output_dir / "aggregate.jsonl", aggregate)
    _write_json(
        output_dir / "manifest.json",
        {
            "schema_version": 1,
            "kind": "context_rich_story_dialogue_machine_draft",
            "writes_canonical_corpus": False,
            "model": args.model,
            "source_queue": str(queue_path.relative_to(PROJECT_ROOT)),
            "source_queue_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
            "candidate_count": len(queue),
            "batch_size": args.batch_size,
            "batch_count": len(receipts),
            "speaker_identity_complete": True,
            "speaker_work_complete": True,
            "adjacent_context_complete": True,
            "strict_passed": True,
        },
    )
    print(
        f"model={args.model} rows={len(aggregate)}/{len(queue)} "
        f"batches={len(receipts)} strict=True"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
