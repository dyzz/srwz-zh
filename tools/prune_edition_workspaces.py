#!/usr/bin/env python3
"""List or remove stale private edition workspaces and input snapshots.

Every build_editions run keeps its private workspace under
``build/editions/<profile>/<run-key>/`` (including a full ISO copy) and its
frozen input snapshot under ``work/build/shared/<input-digest>/``. Nothing
removes them, so they accumulate. This tool keeps:

* every workspace and snapshot referenced by a current edition receipt
  (``manifests/editions/<edition>/current.json``), which the next build seeds
  its caches from;
* the ``--keep`` most recent other workspaces per profile;
* every snapshot still referenced by a kept workspace.

Without ``--apply`` it only prints the plan. Sizes are apparent sizes; APFS
clones share blocks with the current ISOs, so the reclaimed space is smaller.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDITIONS_ROOT = PROJECT_ROOT / "build/editions"
SNAPSHOTS_ROOT = PROJECT_ROOT / "work/build/shared"


def apparent_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def referenced_by_receipts() -> tuple[set[Path], set[str]]:
    runs, digests = set(), set()
    for receipt in (PROJECT_ROOT / "manifests/editions").glob("*/current.json"):
        document = load_json(receipt)
        workspace = document.get("workspace")
        if isinstance(workspace, str):
            run = (PROJECT_ROOT / workspace).resolve()
            if run.name == "project":
                run = run.parent
            runs.add(run)
        digest = document.get("input_digest")
        if isinstance(digest, str):
            digests.add(digest)
    return runs, digests


def plan(keep: int) -> dict:
    keep_runs, keep_digests = referenced_by_receipts()
    stale_runs = []
    if EDITIONS_ROOT.is_dir():
        for profile in sorted(p for p in EDITIONS_ROOT.iterdir() if p.is_dir()):
            runs = sorted((r for r in profile.iterdir() if r.is_dir()),
                          key=lambda r: r.stat().st_mtime, reverse=True)
            recent = 0
            for run in runs:
                if run.resolve() in keep_runs:
                    continue
                if recent < keep:
                    recent += 1
                    keep_runs.add(run.resolve())
                    continue
                stale_runs.append(run)
    for run in keep_runs:
        inputs = load_json(run / "project/work/edition-inputs.json")
        if isinstance(inputs.get("input_digest"), str):
            keep_digests.add(inputs["input_digest"])
    stale_snapshots = []
    if SNAPSHOTS_ROOT.is_dir():
        for snapshot in sorted(SNAPSHOTS_ROOT.iterdir()):
            if snapshot.is_dir() and snapshot.name not in keep_digests and not snapshot.name.startswith("."):
                stale_snapshots.append(snapshot)
    return {"keep_runs": sorted(str(r.relative_to(PROJECT_ROOT)) for r in keep_runs),
            "stale_runs": stale_runs, "stale_snapshots": stale_snapshots}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=int, default=2, help="Recent unreferenced workspaces to keep per profile (default 2).")
    parser.add_argument("--apply", action="store_true", help="Delete the listed directories instead of only printing them.")
    args = parser.parse_args()
    if args.keep < 0:
        parser.error("--keep must be zero or more")
    result = plan(args.keep)
    total = 0
    for label, items in (("workspace", result["stale_runs"]), ("snapshot", result["stale_snapshots"])):
        for item in items:
            size = apparent_size(item)
            total += size
            print(f"[{'delete' if args.apply else 'stale'}] {label} {item.relative_to(PROJECT_ROOT)} ({size / 2**30:.1f} GiB apparent)")
            if args.apply:
                shutil.rmtree(item)
    print(f"kept workspaces: {len(result['keep_runs'])}; stale: {len(result['stale_runs'])} workspaces, "
          f"{len(result['stale_snapshots'])} snapshots, {total / 2**30:.1f} GiB apparent")
    if not args.apply and total:
        print("dry run; add --apply to delete", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
