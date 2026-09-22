#!/usr/bin/env python3
"""Build registered editions from one frozen input set.

Original is also the shared text/layout compiler frontend for BEST. The BEST
backend consumes only a same-snapshot result and its own native disc sources.
No experimental binary-port script or frozen alpha translation is invoked.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

from srwz.edition import BuildContext, EditionError, json_bytes, load_json, load_release_profiles, project_path
from srwz.iso9660 import member_map, scan_iso9660
from srwz.release_inputs import copy_file, freeze_inputs, seed_original_caches, sha256_file, verify_files
from srwz.sp_edition import locked_sp_inputs, validate_sp_readback
from srwz.daily_test import publish_daily_test
from srwz.edition_incremental import seed_text_update


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "config/release/dual-current.json"
LEGACY_CONFIG = "config/iso/zh-release-current-build.json"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(json_bytes(value))
    temporary.replace(path)


@contextmanager
def edition_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise EditionError(f"another build owns this edition: {path}") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def verify_disc(root: Path, profile) -> None:
    path = project_path(root, profile.source_iso.path, "rom")
    if not path.is_file() or path.stat().st_size != profile.source_iso.size or sha256_file(path) != profile.source_iso.sha256:
        raise EditionError(f"{profile.edition_id}: source ISO identity mismatch")
    members = member_map(scan_iso9660(path))
    exe = members.get(profile.executable.path)
    if exe is None or exe.size != profile.executable.size:
        raise EditionError(f"{profile.edition_id}: executable member mismatch")
    with path.open("rb") as source:
        source.seek(exe.extent_lba * 2048)
        digest = hashlib.sha256(source.read(exe.size)).hexdigest()
    if digest != profile.executable.sha256:
        raise EditionError(f"{profile.edition_id}: executable identity mismatch")


def verify_original_adapter_config(root: Path, profile) -> None:
    cfg = load_json(project_path(root, LEGACY_CONFIG, "config/iso"))
    for name in ("path", "size", "sha256"):
        if cfg["source_iso"][name] != getattr(profile.source_iso, name):
            raise EditionError(f"Original adapter/source config mismatch: {name}")
    if profile.executable.path not in {row["member"] for row in cfg["replacements"]}:
        raise EditionError("Original adapter has no matching executable output")


def run_phase(context: BuildContext, name: str, arguments: list[str]) -> None:
    log = context.run_root / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{context.profile.edition_id}] {name}", flush=True)
    started = time.perf_counter()
    with log.open("wb") as output:
        result = subprocess.run([sys.executable, *arguments], cwd=context.project_root,
                                stdout=output, stderr=subprocess.STDOUT)
    elapsed = round(time.perf_counter() - started, 3)
    timings = context.run_root / "timing.json"
    phases = load_json(timings) if timings.exists() else {}
    phases[name] = {"seconds": elapsed, "returncode": result.returncode}
    atomic_json(timings, phases)
    print(f"[{context.profile.edition_id}] {name}: {elapsed:.3f}s", flush=True)
    if result.returncode:
        tail = log.read_text(errors="replace")[-2400:]
        raise EditionError(f"{name} failed; {log}\n{tail}")


def prepare_original_members(context: BuildContext) -> None:
    # This helper only reads explicit config paths; no Git query is needed in
    # the private project. Existing CLI behaviour in the legacy tool is intact.
    from build_text_update_iso import collect_original_member_locks
    root = context.project_root
    # SP export tables include array-root JSON and describe another disc.
    configs = (path for path in (root / "config").rglob("*.json")
               if "special-disc" not in path.relative_to(root / "config").parts)
    locks = collect_original_member_locks(sorted(configs))
    iso = project_path(root, context.profile.source_iso.path, "rom")
    members = member_map(scan_iso9660(iso))
    with iso.open("rb") as source:
        for member, lock in locks.items():
            target = project_path(root, lock["path"], "work/disc")
            if target.is_file() and target.stat().st_size == lock["size"] and sha256_file(target) == lock["sha256"]:
                continue
            row = members.get(member)
            if row is None or row.size != lock["size"]:
                raise EditionError(f"Original input member mismatch: {member}")
            source.seek(row.extent_lba * 2048)
            data = source.read(row.size)
            if hashlib.sha256(data).hexdigest() != lock["sha256"]:
                raise EditionError(f"Original input member hash mismatch: {member}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def reset_relocated_cmake(root: Path, config: dict) -> None:
    source = project_path(root, config["toolchain"]["source_dir"], "work/toolchain")
    directory = project_path(root, (source / "build").relative_to(root).as_posix(), "work/toolchain")
    cache = directory / "CMakeCache.txt"
    if cache.is_file():
        text = cache.read_text(errors="replace")
        if (f"CMAKE_HOME_DIRECTORY:INTERNAL={source}\n" not in text
                or f"CMAKE_CACHEFILE_DIR:INTERNAL={directory}\n" not in text):
            # Only a generated build directory inside this private project.
            # A relocated CMake cache must never direct writes to the old root.
            shutil.rmtree(directory)


def build_original(context: BuildContext, snapshot, *, legacy_equivalence: bool, force_rebuild: bool = False) -> dict:
    root = context.project_root
    root.mkdir(parents=True, exist_ok=True)
    snapshot.materialize(root)
    atomic_json(root / "work/edition-inputs.json", {
        "input_digest": snapshot.digest, "source_head": snapshot.source_head,
        "paths": [r["path"] for r in snapshot.files],
    })
    reused = not force_rebuild and seed_text_update(context, snapshot)
    print(f"[original] previous text-update cache: {'seeded' if reused else 'unavailable'}", flush=True)
    print("[original] prepare private, independently writable caches", flush=True)
    seed_original_caches(context.root, root)
    iso = project_path(root, context.profile.source_iso.path, "rom")
    if not iso.exists():
        copy_file(project_path(context.root, context.profile.source_iso.path, "rom"), iso)
    verify_disc(root, context.profile)
    verify_original_adapter_config(root, context.profile)
    baseline = load_json(root / LEGACY_CONFIG)
    prepare_original_members(context)
    chain = load_json(root / "config/fonts/zh-font-build-chain.json")
    reset_relocated_cmake(root, baseline)
    run_phase(context, "codec", ["tools/build_rust_compressor.py", "--force"])
    run_phase(context, "iso-toolchain", ["tools/bootstrap_mkps2iso.py", "--config", LEGACY_CONFIG])
    run_phase(context, "fonts", ["tools/fetch_zh_font.py", "--flavor", chain["font_flavor"]])
    run_phase(context, "components", ["tools/rebuild_zh_font.py", "--skip-fetch", "--refresh-manifests",
                                      *(["--force-rebuild"] if force_rebuild or not reused else []),
                                      "--cache", "work/cache/editions/original/font-chain.json"])
    run_phase(context, "iso", ["tools/build_iso.py", "--config", LEGACY_CONFIG, "--refresh-output-locks",
                               *(["--refresh-extraction"] if force_rebuild or not reused else ["--incremental"])])
    run_phase(context, "readback", ["tools/verify_full_story_iso_content.py", "--refresh-manifest", *(["--force"] if force_rebuild else []),
                                    "--cache", "work/cache/editions/original/iso-content.json"])
    cfg = load_json(root / LEGACY_CONFIG)
    readback = load_json(root / "manifests/zh-release-full-story-iso-content-validation.json")
    output = project_path(root, cfg["output"]["path"], "build/iso")
    actual_hash = sha256_file(output)
    if (actual_hash != cfg["output"]["expected_sha256"] or actual_hash != readback["iso"]["sha256"]
            or readback["status"] != "full_story_final_iso_static_content_readback_passed"):
        raise EditionError("Original ISO/readback binding mismatch")
    before = {r["member"]: (r["size"], r["sha256"]) for r in baseline["replacements"]}
    after = {r["member"]: (r["size"], r["sha256"]) for r in cfg["replacements"]}
    equivalent = before == after and actual_hash == baseline["output"]["expected_sha256"]
    if legacy_equivalence and not equivalent:
        raise EditionError("new Original entry is not byte-identical to the frozen legacy output locks")
    verify_files(snapshot.project_root, list(snapshot.files))
    context.output_iso.parent.mkdir(parents=True, exist_ok=True)
    pending = context.output_iso.with_suffix(".iso.tmp")
    copy_file(output, pending)
    if sha256_file(pending) != actual_hash:
        pending.unlink()
        raise EditionError("published ISO copy mismatch")
    pending.replace(context.output_iso)
    return {
        "schema_version": 1, "edition_id": context.profile.edition_id,
        "status": "edition_iso_static_validated_runtime_pending",
        "adapter": context.profile.adapter, "input_digest": snapshot.digest,
        "source_head": snapshot.source_head, "edition_contract_sha256": context.profile.contract_sha256,
        "source_iso_sha256": context.profile.source_iso.sha256,
        "output": {"path": context.output_iso.relative_to(context.root).as_posix(), "size": output.stat().st_size, "sha256": actual_hash},
        "legacy_equivalence": {"required": legacy_equivalence, "passed": equivalent,
                               "member_count": len(after), "baseline_iso_sha256": baseline["output"]["expected_sha256"]},
        "readback": {"path": (root / "manifests/zh-release-full-story-iso-content-validation.json").relative_to(context.root).as_posix(),
                     "sha256": sha256_file(root / "manifests/zh-release-full-story-iso-content-validation.json"),
                     "stage_count": readback["stage_count"], "translation_entry_count": readback["translation_entry_count"]},
        "workspace": root.relative_to(context.root).as_posix(), "runtime": "not_tested",
    }


def build_best(context: BuildContext, snapshot, common: BuildContext, common_result: dict) -> dict:
    root = context.project_root
    root.mkdir(parents=True, exist_ok=True)
    snapshot.materialize(root)
    iso = project_path(root, context.profile.source_iso.path, "rom")
    if not iso.exists():
        copy_file(project_path(context.root, context.profile.source_iso.path, "rom"), iso)
    verify_disc(root, context.profile)
    binary = "work/toolchain/srwz-compressor-rs/target/release/srwz-compress"
    copy_file(common.project_root / binary, root / binary)
    receipt = root / "work/common-input.json"
    atomic_json(receipt, common_result)
    run_phase(context, "native-components-and-iso", ["tools/build_best_current.py", "--common-project", str(common.project_root),
              "--common-receipt", str(receipt), "--input-digest", snapshot.digest])
    proof_path = root / "work/build/best-current/iso-readback.json"
    proof = load_json(proof_path)
    if proof["status"] != "best_final_iso_static_content_readback_passed" or proof["input_digest"] != snapshot.digest:
        raise EditionError("BEST final proof/input binding mismatch")
    output = project_path(root, proof["iso"]["path"], "build/iso")
    if output.stat().st_size != proof["iso"]["size"] or sha256_file(output) != proof["iso"]["sha256"]:
        raise EditionError("BEST final ISO identity mismatch")
    verify_files(snapshot.project_root, list(snapshot.files))
    context.output_iso.parent.mkdir(parents=True, exist_ok=True)
    pending = context.output_iso.with_suffix(".iso.tmp")
    copy_file(output, pending)
    if sha256_file(pending) != proof["iso"]["sha256"]:
        pending.unlink()
        raise EditionError("BEST published copy mismatch")
    pending.replace(context.output_iso)
    return {
        "schema_version": 1, "edition_id": "best", "adapter": context.profile.adapter,
        "status": "edition_iso_static_validated_runtime_pending", "input_digest": snapshot.digest,
        "source_head": snapshot.source_head, "edition_contract_sha256": context.profile.contract_sha256,
        "source_iso_sha256": context.profile.source_iso.sha256,
        "output": {**proof["iso"], "path": context.output_iso.relative_to(context.root).as_posix()},
        "readback": {"path": proof_path.relative_to(context.root).as_posix(), "sha256": sha256_file(proof_path),
                     "stage_count": proof["stage_chunk_count"], "translation_entry_count": proof["stage_text_owner_count"]},
        "shared_frontend": {"edition": "original", "input_digest": snapshot.digest,
                            "readback_sha256": common_result["readback"]["sha256"], "iso_sha256": common_result["output"]["sha256"]},
        "workspace": root.relative_to(context.root).as_posix(), "runtime": "not_tested",
    }


def build_sp(context: BuildContext, snapshot) -> dict:
    """Rebuild the current SP corpus over its verified native font baseline."""
    root = context.project_root
    snapshot.materialize(root)
    locked_sp_inputs(root)
    source = context.profile.source_iso.path
    copy_file(context.root / source, root / source)
    verify_disc(root, context.profile)
    run_phase(context, "rust-compressor", ["tools/build_rust_compressor.py", "--force"])
    run_phase(context, "sp-full-text", ["tools/special_disc/writeback/build_full_text.py"])
    # build_full_text verifies the temporary ISO before publishing and binds
    # that independent receipt below; do not execute the same verifier twice.
    proof_path = root / "build/iso/special-disc/sp-current.json"
    proof = load_json(proof_path)
    # The SP publisher pins the readback to this immutable build run. Do not
    # replace that binding with a report from the legacy reusable directory.
    validate_sp_readback(root, proof)
    verify_files(snapshot.project_root, list(snapshot.files))
    # SP builders must never mutate the captured source/baseline inputs.
    verify_files(root, list(snapshot.files))
    built = project_path(root, proof["iso"]["path"], "build/iso/special-disc")
    context.output_iso.parent.mkdir(parents=True, exist_ok=True)
    temporary = context.output_iso.with_suffix(".tmp.iso")
    copy_file(built, temporary)
    if sha256_file(temporary) != proof["iso"]["sha256"]:
        raise EditionError("SP promotion copy drift")
    temporary.replace(context.output_iso)
    atomic_json(context.output_iso.with_suffix(".json"), proof)
    return {
        "schema_version": 1, "edition_id": "sp", "adapter": context.profile.adapter,
        "status": "edition_iso_static_validated_runtime_pending", "input_digest": snapshot.digest,
        "source_head": snapshot.source_head, "edition_contract_sha256": context.profile.contract_sha256,
        "source_iso_sha256": context.profile.source_iso.sha256,
        "output": {**proof["iso"], "path": context.output_iso.relative_to(context.root).as_posix()},
        "readback": {"path": proof_path.relative_to(context.root).as_posix(), "sha256": sha256_file(proof_path)},
        "workspace": root.relative_to(context.root).as_posix(), "runtime": "not_tested",
    }


def build(root: Path, config: str, requested: tuple[str, ...], *, plan: bool = False, legacy_equivalence: bool = False, force_rebuild: bool = False) -> dict:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    root = root.resolve()
    profiles = load_release_profiles(root, config, requested)
    dependencies = load_release_profiles(root, config, ("original",)) if "best" in requested and "original" not in requested else ()
    build_profiles = {p.edition_id: p for p in (*dependencies, *profiles)}
    if plan:
        return {"status": "plan_only", "writes": False, "targets": [
            {"edition": p.edition_id, "adapter": p.adapter, "available": p.adapter is not None,
             "source_iso": p.source_iso.path, "executable": p.executable.path, "profile_id": p.profile_id}
            for p in profiles]}
    # Preflight all targets first; never partially build Original when BEST is
    # requested but unsupported, and never silently route BEST through Original.
    for profile in build_profiles.values():
        profile.require_supported()
    for profile in build_profiles.values():
        context = BuildContext(root, profile, "0" * 64)
        # Reject aliases of another edition or the legacy output before I/O.
        for field in ("project_root", "cache_root", "output_iso", "receipt"):
            getattr(context, field)
    for profile in build_profiles.values():
        if profile.edition_id == "original":
            verify_original_adapter_config(root, profile)
        verify_disc(root, profile)
    with ExitStack() as stack:
        for profile in sorted(build_profiles.values(), key=lambda p: p.edition_id):
            stack.enter_context(edition_lock(project_path(root, f"work/cache/editions/{profile.edition_id}/build.lock", "work/cache")))
        additional = locked_sp_inputs(root) if "sp" in build_profiles else ()
        snapshot = freeze_inputs(root, additional)
        if load_release_profiles(snapshot.project_root, config, tuple(build_profiles)) != tuple(build_profiles.values()):
            raise EditionError("edition contracts changed during input capture")
        contexts = {name: BuildContext(root, profile, snapshot.digest) for name, profile in build_profiles.items()}
        for context in contexts.values():
            context.project_root  # Also check aliases under this exact input key.
        batch_path = project_path(root, f"work/editions/{snapshot.digest}/{'-'.join(requested)}.json", "work")
        batch = {"schema_version": 1, "input_digest": snapshot.digest, "requested_editions": list(requested),
                 "release_config": config, "input_snapshot": (snapshot.root / "inputs.json").relative_to(root).as_posix(),
                 "status": "running", "results": [], "runtime": "not_tested",
                 "timing": {"started_at": started_at, "preflight_and_snapshot_seconds": round(time.perf_counter() - started, 3), "editions": {}}}
        atomic_json(batch_path, batch)
        def run_edition(context, builder, *args, **kwargs):
            begin = time.perf_counter()
            timing_path = context.run_root / "timing.json"
            timing_path.unlink(missing_ok=True)
            mode = "build"
            try:
                if not force_rebuild and not legacy_equivalence and context.receipt.is_file():
                    previous = load_json(context.receipt)
                    frontend_matches = context.profile.edition_id != "best" or previous.get("shared_frontend") == {
                        "edition": "original", "input_digest": snapshot.digest,
                        "readback_sha256": args[-1].get("readback", {}).get("sha256"),
                        "iso_sha256": args[-1].get("output", {}).get("sha256"),
                    }
                    if previous.get("input_digest") == snapshot.digest and frontend_matches:
                        from verify_editions import verify_batch
                        probe = context.run_root / "reuse-check.json"
                        atomic_json(probe, {**batch, "status": "requested_editions_static_validated_runtime_pending",
                            "requested_editions": [context.profile.edition_id], "results": [previous]})
                        try:
                            verify_batch(root, probe)
                        except (OSError, ValueError, KeyError):
                            print(f"[{context.profile.edition_id}] current receipt/copy cannot be reused", flush=True)
                        else:
                            if "daily_test" in previous:
                                mode = "verified_current_reuse"
                                publication = 0.0
                                print(f"[{context.profile.edition_id}] unchanged inputs and verified current/daily ISOs reused", flush=True)
                                return previous
                result = builder(context, *args, **kwargs)
                # Bind the promoted current ISO immediately, even if publishing
                # its daily copy subsequently fails.
                atomic_json(context.receipt, result)
                publish_begin = time.perf_counter()
                result["daily_test"] = publish_daily_test(root, snapshot.project_root, result)
                atomic_json(context.receipt, result)
                publication = round(time.perf_counter() - publish_begin, 3)
                return result
            finally:
                batch["timing"]["editions"][context.profile.edition_id] = {
                    "seconds": round(time.perf_counter() - begin, 3),
                    "mode": mode,
                    "phases": load_json(timing_path) if timing_path.exists() else {},
                    "daily_test_seconds": locals().get("publication"),
                }
        try:
            results = {}
            # One frontend execution even for reversed target order or BEST-only.
            if "original" in contexts:
                original = contexts["original"]
                results["original"] = run_edition(original, build_original, snapshot, legacy_equivalence=legacy_equivalence, force_rebuild=force_rebuild)
                atomic_json(original.receipt, results["original"])
            if "best" in contexts:
                results["best"] = run_edition(contexts["best"], build_best, snapshot, original, results["original"])
                atomic_json(contexts["best"].receipt, results["best"])
            if "sp" in contexts:
                results["sp"] = run_edition(contexts["sp"], build_sp, snapshot)
                atomic_json(contexts["sp"].receipt, results["sp"])
            for name in requested:
                context, result = contexts[name], results[name]
                batch["results"].append(result)
                atomic_json(batch_path, batch)
        except Exception as error:
            batch.update(status="failed", error=str(error))
            batch["timing"]["total_seconds"] = round(time.perf_counter() - started, 3)
            atomic_json(batch_path, batch)
            raise
        batch["status"] = "requested_editions_static_validated_runtime_pending"
        batch["timing"].update(total_seconds=round(time.perf_counter() - started, 3), finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(batch_path, batch)
        return {**batch, "batch_manifest": batch_path.relative_to(root).as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--editions", default="original,best,sp")
    parser.add_argument("--plan", action="store_true", help="Show registered targets without writing or building.")
    parser.add_argument("--force-rebuild", action="store_true", help="Explicit full Original rebuild and uncached readback; normal builds reuse verified text components.")
    parser.add_argument("--require-legacy-equivalence", action="store_true", help="Fail before promotion unless all Original component and ISO bytes match the frozen legacy locks.")
    args = parser.parse_args()
    try:
        result = build(PROJECT_ROOT, args.config, tuple(x.strip() for x in args.editions.split(",")),
                       plan=args.plan, legacy_equivalence=args.require_legacy_equivalence, force_rebuild=args.force_rebuild)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (EditionError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
