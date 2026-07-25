#!/usr/bin/env python3
"""Audit pinned binary patch outputs without saving any game bytes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.patch_audit import PatchAuditError, audit_binary_patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONTRACT = (
    PROJECT_ROOT / "config" / "patches" / "upstream-asm-audit.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify pinned input/output hashes, exact changed-byte sets, "
            "declared write ranges and explicit overlaps."
        )
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT,
    )
    parser.add_argument(
        "--target",
        action="append",
        help="target id to audit; repeat as needed (default: all)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=WORK_ROOT / "patch-audit" / "audit-report.json",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _resolve_repo_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_contract(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise PatchAuditError("unsupported patch-audit schema")
    targets = document.get("targets")
    if not isinstance(targets, list) or not targets:
        raise PatchAuditError("patch-audit contract has no targets")
    ids = [target.get("id") for target in targets]
    if any(not isinstance(target_id, str) for target_id in ids):
        raise PatchAuditError("patch-audit target id is invalid")
    if len(ids) != len(set(ids)):
        raise PatchAuditError("patch-audit target ids are not unique")
    return document


def audit_contract_target(target: dict) -> dict:
    before_path = _resolve_repo_path(target["before_path"])
    after_path = _resolve_repo_path(target["after_path"])
    owners = target.get("owners", {})
    owner_outputs = {
        owner: _resolve_repo_path(expected["output_path"]).read_bytes()
        for owner, expected in owners.items()
    }
    report = audit_binary_patch(
        before_path.read_bytes(),
        after_path.read_bytes(),
        target,
        owner_outputs=owner_outputs,
    )
    return {
        "id": target["id"],
        "script": target["script"],
        "status": "pass",
        **report,
    }


def main() -> int:
    args = parse_args()
    output = require_work_output(args.json_output, WORK_ROOT)
    if output.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {output}")

    contract = load_contract(args.contract)
    targets = {
        target["id"]: target for target in contract["targets"]
    }
    requested = args.target or list(targets)
    unknown = sorted(set(requested) - set(targets))
    if unknown:
        raise SystemExit(f"unknown patch-audit targets: {unknown}")

    reports = []
    for target_id in requested:
        print(f"audit {target_id} ...")
        reports.append(audit_contract_target(targets[target_id]))

    document = {
        "schema_version": 1,
        "content_policy": (
            "Hashes, counts and offset-set digests only; no original or "
            "patched game bytes are embedded."
        ),
        "status": "pass",
        "target_count": len(reports),
        "targets": reports,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"json: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
