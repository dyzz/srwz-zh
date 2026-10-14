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
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from srwz.edition import BuildContext, EditionError, json_bytes, load_json, load_release_profiles, project_path
from srwz.codec import ENV_COMPRESSION_CACHE, prune_compression_cache
from srwz.file_identity import ENV_STORE, publish_verified, sha256_range
from srwz.iso9660 import member_map, scan_iso9660
from srwz.release_inputs import (INTEGRATED_COMPONENT_BUILD_DIRS, copy_file, freeze_inputs,
                                 seed_original_caches, sha256_file, verify_files)
from srwz.sp_edition import locked_sp_inputs, validate_sp_readback
from srwz.current_iso import verify_skip
from srwz.edition_incremental import seed_text_update


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = "config/release/dual-current.json"
LEGACY_CONFIG = "config/iso/zh-release-current-build.json"
CAPTION_FONT = "work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf"


def base_output(result: dict) -> dict:
    """The image an edition's semantic readback is bound to (before captions)."""
    return result.get("base_output") or result["output"]


def file_lock(root: Path, path: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)}


def apply_main_event_subtitles(context: BuildContext, base_iso: Path, font: Path) -> tuple[Path, dict]:
    """Final Original/Best stage: native map-effect captions on the verified image.

    The semantic readback stays bound to ``base_iso``. The executable and
    effect archive grow, so they are appended after the base image and every
    other base byte is proven unchanged; the receipt binds base and final.
    """
    from event_subtitles.apply import ARCHIVE, apply_event_subtitles, load_profile, verify_subtitle_members
    from special_disc.iso_relocation import append_members, verify_relocation, verify_untouched
    root, edition = context.project_root, context.profile.edition_id
    profile = load_profile(edition, root)
    before = member_map(scan_iso9660(base_iso))
    with base_iso.open("rb") as stream:
        inputs = {}
        for name in (profile["elf_member"], ARCHIVE):
            stream.seek(before[name].extent_lba * 2048)
            inputs[name] = stream.read(before[name].size)
    workdir = context.run_root / "event-subtitles"
    result = apply_event_subtitles(edition, inputs[profile["elf_member"]], inputs[ARCHIVE],
                                   workdir=workdir, font=font, root=root, profile=profile)
    final = base_iso.with_name(base_iso.stem + "-captioned.iso")
    final.unlink(missing_ok=True)
    copy_file(base_iso, final)
    relocation = append_members(final, before, result["members"],
                                allowed_udf={profile["elf_member"], ARCHIVE}, catalog_policy="inherit")
    readback = verify_relocation(final, before, result["members"], relocation)
    untouched = verify_untouched(base_iso, final, relocation["touched_spans"])
    members = verify_subtitle_members(result["members"][profile["elf_member"]], result["members"][ARCHIVE],
                                      profile, result["receipt"])
    receipt = {"schema_version": 1, "base_iso": file_lock(root, base_iso), "iso": file_lock(root, final),
               "members": {name: hashlib.sha256(data).hexdigest() for name, data in result["members"].items()},
               "relocation": relocation, "relocation_readback": readback, "untouched_base_bytes": untouched,
               "member_readback": members, "subtitles": result["receipt"],
               "runtime": "not_tested"}
    atomic_json(workdir / "receipt.json", receipt)
    return final, receipt


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
    if sha256_range(path, exe.extent_lba * 2048, exe.size) != profile.executable.sha256:
        raise EditionError(f"{profile.edition_id}: executable identity mismatch")


def verify_original_adapter_config(root: Path, profile) -> None:
    cfg = load_json(project_path(root, LEGACY_CONFIG, "config/iso"))
    for name in ("path", "size", "sha256"):
        if cfg["source_iso"][name] != getattr(profile.source_iso, name):
            raise EditionError(f"Original adapter/source config mismatch: {name}")
    if profile.executable.path not in {row["member"] for row in cfg["replacements"]}:
        raise EditionError("Original adapter has no matching executable output")


def phase_environment(root: Path) -> dict[str, str]:
    """Every subprocess of one build shares the root's identity and payload stores."""
    environment = dict(os.environ)
    environment.setdefault(ENV_STORE, str(project_path(root, "work/cache/file-identity.json", "work/cache")))
    environment.setdefault(ENV_COMPRESSION_CACHE, str(project_path(root, "work/cache/compression", "work/cache")))
    return environment


def run_phase(context: BuildContext, name: str, arguments: list[str]) -> None:
    log = context.run_root / "logs" / f"{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{context.profile.edition_id}] {name}", flush=True)
    started = time.perf_counter()
    with log.open("wb") as output:
        result = subprocess.run([sys.executable, *arguments], cwd=context.project_root,
                                stdout=output, stderr=subprocess.STDOUT, env=phase_environment(context.root))
    elapsed = round(time.perf_counter() - started, 3)
    _record_timing(context, name, elapsed, result.returncode)
    if result.returncode:
        tail = log.read_text(errors="replace")[-2400:]
        raise EditionError(f"{name} failed; {log}\n{tail}")


_TIMING_LOCK = threading.Lock()


def _record_timing(context: BuildContext, name: str, elapsed: float, returncode: int) -> None:
    # Phases of one edition may finish from different threads (the layout
    # extraction overlaps the components); the read-modify-write is serialized.
    with _TIMING_LOCK:
        timings = context.run_root / "timing.json"
        phases = load_json(timings) if timings.exists() else {}
        phases[name] = {"seconds": elapsed, "returncode": returncode}
        atomic_json(timings, phases)
    print(f"[{context.profile.edition_id}] {name}: {elapsed:.3f}s", flush=True)


def record_phase(context: BuildContext, name: str, started: float) -> None:
    """Timing entry for an in-process stage, alongside subprocess phases."""
    _record_timing(context, name, round(time.perf_counter() - started, 3), 0)


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
            # Only generated CMake state inside this private project. A relocated
            # cache must never direct writes to the old root; the already built
            # executables are inert files that the bootstrap re-verifies by
            # pinned commit and version line before reusing them.
            cache.unlink()
            shutil.rmtree(directory / "CMakeFiles", ignore_errors=True)


def build_original(context: BuildContext, snapshot, *, legacy_equivalence: bool, force_rebuild: bool = False) -> dict:
    root = context.project_root
    root.mkdir(parents=True, exist_ok=True)
    snapshot.materialize(root)
    atomic_json(root / "work/edition-inputs.json", {
        "input_digest": snapshot.digest, "source_head": snapshot.source_head,
        "paths": [r["path"] for r in snapshot.files],
    })
    # The previous validated run's component caches, generated locks and ISO
    # baseline are carried forward unless a component build definition changed.
    # When they are unavailable the component pipeline still applies its own
    # per-consumer verified caches; only an explicit --force-rebuild disables them.
    reused = not force_rebuild and seed_text_update(context, snapshot)
    print(f"[original] previous validated component caches: {'seeded' if reused else 'unavailable'}", flush=True)
    print("[original] prepare private, independently writable caches", flush=True)
    # Without a validated seed the integrated component root must start empty:
    # the main checkout's copy is not bound to this snapshot, and the component
    # builder then bootstraps a complete build from its per-consumer caches.
    seed_original_caches(context.root, root,
                         exclude_build_dirs=() if reused else INTEGRATED_COMPONENT_BUILD_DIRS)
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
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="srwz-iso-extract") as pool:
        # A full rebuild re-extracts the 3.7 GB disc layout; that depends on
        # the source disc and toolchain only, so it overlaps the components.
        extraction = (pool.submit(run_phase, context, "iso-extract", ["tools/build_iso.py", "--config", LEGACY_CONFIG,
                                                                     "--refresh-extraction", "--extract-only"])
                      if force_rebuild else None)
        run_phase(context, "components", ["tools/rebuild_zh_font.py", "--skip-fetch", "--refresh-manifests",
                                          *(["--force-rebuild"] if force_rebuild else []),
                                          "--cache", "work/cache/editions/original/font-chain.json"])
        if extraction is not None:
            extraction.result()
    run_phase(context, "iso", ["tools/build_iso.py", "--config", LEGACY_CONFIG, "--refresh-output-locks",
                               *([] if force_rebuild else ["--incremental"])])
    cfg = load_json(root / LEGACY_CONFIG)
    output = project_path(root, cfg["output"]["path"], "build/iso")
    # The captions only need the assembled base image; they are relocated
    # members with their own base->final binding, so they overlap the readback.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="srwz-captions") as pool:
        caption_started = time.perf_counter()
        captions = pool.submit(apply_main_event_subtitles, context, output, root / CAPTION_FONT)
        run_phase(context, "readback", ["tools/verify_full_story_iso_content.py", "--refresh-manifest", *(["--force"] if force_rebuild else []),
                                        "--cache", "work/cache/editions/original/iso-content.json"])
    readback = load_json(root / "manifests/zh-release-full-story-iso-content-validation.json")
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
    final, subtitles = captions.result()
    record_phase(context, "event-subtitles", caption_started)
    context.output_iso.parent.mkdir(parents=True, exist_ok=True)
    pending = context.output_iso.with_suffix(".iso.tmp")
    copy_file(final, pending)
    if sha256_file(pending) != subtitles["iso"]["sha256"]:
        pending.unlink()
        raise EditionError("published ISO copy mismatch")
    publish_verified(pending, context.output_iso, subtitles["iso"]["sha256"])
    return {
        "schema_version": 1, "edition_id": context.profile.edition_id,
        "status": "edition_iso_static_validated_runtime_pending",
        "adapter": context.profile.adapter, "input_digest": snapshot.digest,
        "source_head": snapshot.source_head, "edition_contract_sha256": context.profile.contract_sha256,
        "source_iso_sha256": context.profile.source_iso.sha256,
        "output": {"path": context.output_iso.relative_to(context.root).as_posix(), "size": final.stat().st_size, "sha256": subtitles["iso"]["sha256"]},
        "base_output": {"path": output.relative_to(root).as_posix(), "size": output.stat().st_size, "sha256": actual_hash},
        "event_subtitles": subtitles,
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
    atomic_json(receipt, {**common_result, "output": base_output(common_result)})
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
    # The caption font is a seeded cache of the shared frontend workspace.
    copy_file(common.project_root / CAPTION_FONT, root / CAPTION_FONT)
    run_phase_started = time.perf_counter()
    final, subtitles = apply_main_event_subtitles(context, output, root / CAPTION_FONT)
    record_phase(context, "event-subtitles", run_phase_started)
    context.output_iso.parent.mkdir(parents=True, exist_ok=True)
    pending = context.output_iso.with_suffix(".iso.tmp")
    copy_file(final, pending)
    if sha256_file(pending) != subtitles["iso"]["sha256"]:
        pending.unlink()
        raise EditionError("BEST published copy mismatch")
    publish_verified(pending, context.output_iso, subtitles["iso"]["sha256"])
    return {
        "schema_version": 1, "edition_id": "best", "adapter": context.profile.adapter,
        "status": "edition_iso_static_validated_runtime_pending", "input_digest": snapshot.digest,
        "source_head": snapshot.source_head, "edition_contract_sha256": context.profile.contract_sha256,
        "source_iso_sha256": context.profile.source_iso.sha256,
        "output": {"path": context.output_iso.relative_to(context.root).as_posix(), "size": final.stat().st_size, "sha256": subtitles["iso"]["sha256"]},
        "base_output": {**proof["iso"], "path": output.relative_to(root).as_posix()},
        "event_subtitles": subtitles,
        "readback": {"path": proof_path.relative_to(context.root).as_posix(), "sha256": sha256_file(proof_path),
                     "stage_count": proof["stage_chunk_count"], "translation_entry_count": proof["stage_text_owner_count"]},
        "shared_frontend": {"edition": "original", "input_digest": snapshot.digest,
                            "readback_sha256": common_result["readback"]["sha256"], "iso_sha256": base_output(common_result)["sha256"]},
        "workspace": root.relative_to(context.root).as_posix(), "runtime": "not_tested",
    }


def build_sp(context: BuildContext, snapshot, *, force_rebuild: bool = False) -> dict:
    """Rebuild the current SP corpus over its verified native font baseline."""
    root = context.project_root
    snapshot.materialize(root)
    locked_sp_inputs(root)
    source = context.profile.source_iso.path
    copy_file(context.root / source, root / source)
    verify_disc(root, context.profile)
    if not force_rebuild and context.receipt.is_file():
        from special_disc.writeback.incremental import CACHE_PATH, seed_components
        previous = load_json(context.receipt)
        if (previous.get('status') == 'edition_iso_static_validated_runtime_pending'
                and previous.get('edition_contract_sha256') == context.profile.contract_sha256):
            previous_root = project_path(context.root, previous['workspace'], 'build/editions')
            previous_report = project_path(context.root, previous['readback']['path'], previous['workspace'])
            seeded = seed_components(previous_root, previous_report, previous['readback']['sha256'], root / CACHE_PATH)
            print(f'[sp] previous verified components: {"seeded" if seeded else "unavailable"}', flush=True)
    codec_target = context.root / "work/toolchain/srwz-compressor-rs"
    if codec_target.is_dir() and not (root / "work/toolchain/srwz-compressor-rs").exists():
        # Optional warm Cargo target only; cargo --locked still rebuilds anything stale.
        shutil.copytree(codec_target, root / "work/toolchain/srwz-compressor-rs", copy_function=copy_file)
    run_phase(context, "rust-compressor", ["tools/build_rust_compressor.py", "--force"])
    run_phase(context, "sp-full-text", ["tools/special_disc/writeback/build_full_text.py",
                                      *(["--force-rebuild"] if force_rebuild else [])])
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
    publish_verified(temporary, context.output_iso, proof["iso"]["sha256"])
    atomic_json(context.output_iso.with_suffix(".json"), proof)
    return {
        "schema_version": 1, "edition_id": "sp", "adapter": context.profile.adapter,
        "status": "edition_iso_static_validated_runtime_pending", "input_digest": snapshot.digest,
        "source_head": snapshot.source_head, "edition_contract_sha256": context.profile.contract_sha256,
        "source_iso_sha256": context.profile.source_iso.sha256,
        "output": {**proof["iso"], "path": context.output_iso.relative_to(context.root).as_posix()},
        "readback": {"path": proof_path.relative_to(context.root).as_posix(), "sha256": sha256_file(proof_path)},
        "workspace": root.relative_to(context.root).as_posix(), "runtime": "not_tested",
        "component_modes": {name: row['mode'] for name, row in proof.get('incremental', {}).get('components', {}).items()},
        "event_gallery": {key: proof['event_gallery'][key] for key in ('scene_count', 'caption_count', 'elf_sha256')}
                         if 'event_gallery' in proof else None,
    }


def build(root: Path, config: str, requested: tuple[str, ...], *, plan: bool = False, legacy_equivalence: bool = False, force_rebuild: bool = False) -> dict:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    root = root.resolve()
    if force_rebuild:
        # Trust no file identity recorded before this batch: start the batch
        # from an empty store. Digests this batch verifies (restored baselines,
        # assembled images) still flow to its child processes through it.
        rebuild_store = project_path(root, "work/cache/file-identity-rebuild.json", "work/cache")
        rebuild_store.unlink(missing_ok=True)
        os.environ[ENV_STORE] = str(rebuild_store)
    # In-process stages (caption relocation, receipt hashing) share the same
    # identity store and compression payload cache as the phase subprocesses.
    os.environ.update(phase_environment(root))
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
                        "iso_sha256": base_output(args[-1]).get("sha256") if "output" in args[-1] else None,
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
                            previous.pop("daily_test", None)
                            mode = "verified_current_reuse"
                            print(f"[{context.profile.edition_id}] unchanged inputs and verified current ISO reused", flush=True)
                            return previous
                result = builder(context, *args, **kwargs)
                # Keep one current image per edition. Square skip is already
                # part of its build; verify that image instead of cloning it.
                atomic_json(context.receipt, result)
                result["battle_square_skip"] = verify_skip(
                    context.output_iso, snapshot.project_root, context.profile.edition_id)
                result["skip_enabled"] = True
                atomic_json(context.receipt, result)
                return result
            finally:
                batch["timing"]["editions"][context.profile.edition_id] = {
                    "seconds": round(time.perf_counter() - begin, 3),
                    "mode": mode,
                    "phases": load_json(timing_path) if timing_path.exists() else {},
                }
        try:
            results = {}
            # SP shares nothing with the main editions but the payload cache and
            # the identity store (both safe for concurrent writers), so it runs
            # beside the Original -> BEST chain; the pool exit waits for it even
            # when the chain fails, so the batch records every outcome.
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="srwz-edition-sp") as pool:
                sp_future = (pool.submit(run_edition, contexts["sp"], build_sp, snapshot, force_rebuild=force_rebuild)
                             if "sp" in contexts else None)
                # One frontend execution even for reversed target order or BEST-only.
                if "original" in contexts:
                    original = contexts["original"]
                    results["original"] = run_edition(original, build_original, snapshot, legacy_equivalence=legacy_equivalence, force_rebuild=force_rebuild)
                    atomic_json(original.receipt, results["original"])
                if "best" in contexts:
                    results["best"] = run_edition(contexts["best"], build_best, snapshot, original, results["original"])
                    atomic_json(contexts["best"].receipt, results["best"])
            if sp_future is not None:
                results["sp"] = sp_future.result()
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
        prune_compression_cache(project_path(root, "work/cache/compression", "work/cache"))
        # Each run leaves a private workspace with a full ISO copy; keep the
        # receipt-referenced one plus two recent ones per locked profile.
        from prune_edition_workspaces import prune
        try:
            removed = prune(root, 2, profiles={p.profile_id for p in build_profiles.values()},
                            snapshot_min_age=6 * 3600)
        except OSError as error:
            print(f"[prune] skipped: {error}", file=sys.stderr, flush=True)
        else:
            print(f"[prune] removed {removed['workspaces']} workspaces, {removed['snapshots']} snapshots "
                  f"({removed['apparent_bytes'] / 2**30:.1f} GiB apparent)", flush=True)
        batch["status"] = "requested_editions_static_validated_runtime_pending"
        batch["timing"].update(total_seconds=round(time.perf_counter() - started, 3), finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(batch_path, batch)
        return {**batch, "batch_manifest": batch_path.relative_to(root).as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--editions", default="original,best,sp")
    parser.add_argument("--plan", action="store_true", help="Show registered targets without writing or building.")
    parser.add_argument("--release-version", help="Official release version for the title badge, e.g. 0.5.0; defaults to HEAD tag or latest release + date.")
    parser.add_argument("--force-rebuild", action="store_true", help="Explicit full Original and SP component rebuild, disc re-extraction, uncached readback and re-hashing of every input; normal builds reuse verified components and file identities.")
    parser.add_argument("--require-legacy-equivalence", action="store_true", help="Fail before promotion unless all Original component and ISO bytes match the frozen legacy locks.")
    args = parser.parse_args()
    try:
        if not args.plan and any(x.strip() in ('original', 'best') for x in args.editions.split(',')):
            from freeze_title_version import refresh_current_badge
            import re
            if args.release_version and not re.fullmatch(r'\d+\.\d+\.\d+', args.release_version):
                raise ValueError('release version must be x.y.z')
            text = f'v{args.release_version}' if args.release_version else None
            print(f'[title] version: {refresh_current_badge(PROJECT_ROOT, text=text)}', flush=True)
        result = build(PROJECT_ROOT, args.config, tuple(x.strip() for x in args.editions.split(",")),
                       plan=args.plan, legacy_equivalence=args.require_legacy_equivalence, force_rebuild=args.force_rebuild)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (EditionError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
