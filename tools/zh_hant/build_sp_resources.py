"""Compile three SP regional resource sets and lay them out on one retail-based disc."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.release_inputs import source_inventory, copy_file
from srwz.sp_edition import locked_sp_inputs
from srwz.language import _answer_key
from srwz.file_identity import sha256_file
from special_disc.resource_view import ResourceView, ENV
from build_editions import edition_lock, phase_environment
import assemble_dual
from language_view import place_sp_support
from build_dual import texture_sources

REGIONS = ("sc", "tw", "hk")
CACHE = ROOT / "work/build/sp-multilang-resources"


def input_state(region, badge, component_frontends):
    language = "" if region == "sc" else "zh-hant-" + region
    rows = source_inventory(ROOT, locked_sp_inputs(ROOT), language=language)

    def frontend(r):
        lang = "" if r == "sc" else "zh-hant-" + r
        if not component_frontends:
            return _answer_key(ROOT, lang, True)
        # True: the SP-only frontends; a directory: receipts the Original candidate builds wrote when
        # their components were ready (build_multilang.py compiles SP beside the rest of those builds)
        receipts = (
            ROOT / "work/cache/editions/sp-frontends"
            if component_frontends is True
            else Path(component_frontends)
        )
        receipt = json.loads((receipts / f"{lang or 'zh'}.json").read_text())
        return (
            ROOT / receipt["workspace"] / "work/build/zh-release-full-story/components"
        )

    keys = (
        {r: frontend(r) for r in dict.fromkeys((region, "tw", "sc"))}
        if language
        else {}
    )
    # A frontend is a set of member bytes. Its workspace name alone does not prove them.
    # The converters consume disc members. Diagnostic reports and preview PNGs
    # next to them can change when a source is edited without changing any member.
    config = json.loads((ROOT / "config/iso/zh-release-current-build.json").read_text())
    members = sorted(row["member"] for row in config["replacements"])
    external = {
        r: [(member, sha256_file(key / member)) for member in members]
        for r, key in keys.items()
    }
    from build_dual_sp import SP_FILES, SP_ISO
    from language_view import SP_SUPPORT_TREES

    support = [ROOT / f for f in SP_FILES]
    for dirname in (*SP_SUPPORT_TREES, "config/editorial/special-disc"):
        for f in (ROOT / dirname).rglob("*"):
            rel = f.relative_to(ROOT / dirname)
            if dirname == "work/build/special-disc" and rel.parts[0].startswith(
                "full-text"
            ):
                continue
            if f.is_file() and "__pycache__" not in rel.parts:
                support.append(f)
    support.extend((ROOT / "rom/original.iso", ROOT / SP_ISO))
    external["support"] = [
        (str(f.relative_to(ROOT)), sha256_file(f)) for f in sorted(support)
    ]
    keyed_rows = rows
    taiwan_subtitles = "corpus/zh-hant/special-disc/battle-lines.json"
    if region == "hk" and taiwan_subtitles not in texture_sources():
        # Hong Kong compiles its own subtitles and Data Link page.
        keyed_rows = [row for row in rows if row["path"] != taiwan_subtitles]
    fingerprint = hashlib.sha256(
        json.dumps([keyed_rows, external, badge], sort_keys=True).encode()
    ).hexdigest()
    return rows, keys, fingerprint


class FrontendsUnavailable(RuntimeError):
    """The Original builds did not rebuild their frontends (an `abort` file ended the wait)."""


def compile_region(region, force, badge, component_frontends, await_frontends=False):
    """One region's resources, sealed under the fingerprint of everything they were compiled from.

    ``await_frontends``: the Original frontends named by ``component_frontends`` (a receipt directory) are still
    being built. A Traditional region then starts in a holding directory, runs every step that does not read
    them, and takes its fingerprint (and its place in the cache) once they exist."""
    started = time.monotonic()
    language = "" if region == "sc" else "zh-hant-" + region
    staged = bool(await_frontends) and region != "sc"
    receipts = Path(component_frontends) if staged else None

    def reusable(directory):
        seal = directory / "verified.json"
        if not seal.exists() or force:
            return None
        try:
            doc = json.loads(seal.read_text())
            view = ResourceView.load(directory / doc["path"])
            matches = view.digest(recompute=True) == doc["sha256"]
        except (OSError, ValueError, KeyError):
            matches = False
        if not matches:
            return None
        seal.touch()
        print(f"[{region}] verified resources reused {time.monotonic() - started:.2f}s", flush=True)
        return view

    if staged:
        rows = source_inventory(ROOT, locked_sp_inputs(ROOT), language=language)
        (CACHE / region).mkdir(parents=True, exist_ok=True)
        holding = Path(tempfile.mkdtemp(prefix=".staging-", dir=CACHE / region))
        project = holding / ("inputs-" + holding.name[len(".staging-"):])
        directory = keys = fingerprint = None
    else:
        rows, keys, fingerprint = input_state(region, badge, component_frontends)
        directory = CACHE / region / fingerprint
        view = reusable(directory)
        if view is not None:
            return view
        directory.mkdir(parents=True, exist_ok=True)
        holding = None
        project = Path(tempfile.mkdtemp(prefix="inputs-", dir=directory))
    for row in rows:
        copy_file(ROOT / row["path"], project / row["path"])
    log = project / "build.log"
    env = phase_environment(ROOT)
    env[ENV] = "1"
    if not force and region != "sc":
        env["SRWZ_SP_VIEW_CACHE"] = str(
            ROOT / "work/cache/editions/sp-views" / ("zh-hant-" + region)
        )

    def start(*args):
        out = log.open("a")
        return subprocess.Popen([sys.executable, *map(str, args)], cwd=project, env=env,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True), out

    def finish(process, out):
        code = process.wait()
        out.close()
        if code:
            raise RuntimeError(f"{region}: {log}\n{log.read_text()[-2500:]}")

    def run(*args):
        finish(*start(*args))

    view_tool = (ROOT / "tools/zh_hant/language_view.py", project, "--variant", region, "--editions", "sp")
    try:
        if staged:
            process, out = start(*view_tool, "--frontend-receipts", receipts)
            names = [f"{lang or 'zh'}.json" for lang in dict.fromkeys((language, "zh-hant-tw", ""))]
            while not all((receipts / name).is_file() for name in names):
                if (receipts / "abort").exists() or process.poll() is not None:
                    break
                time.sleep(0.2)
            if not all((receipts / name).is_file() for name in names):
                if process.poll() is None:
                    os.killpg(process.pid, 15)
                process.wait()
                out.close()
                raise FrontendsUnavailable(f"{region}: no Original frontend to compile from")
            current, keys, fingerprint = input_state(region, badge, component_frontends)
            if current != rows:
                os.killpg(process.pid, 15)
                process.wait()
                out.close()
                raise ValueError("build inputs changed during SP compilation")
            directory = CACHE / region / fingerprint
            view = reusable(directory)
            if view is not None:
                # these inputs were compiled before: the work done so far was only the wait
                if process.poll() is None:
                    os.killpg(process.pid, 15)
                process.wait()
                out.close()
                return view
            finish(process, out)
        elif region != "sc":
            run(*view_tool, "--answer-key", keys[region], "--taiwan-answer-key", keys["tw"],
                "--simplified-answer-key", keys["sc"])
        else:
            place_sp_support(project)
        if badge:
            from freeze_title_version import refresh_current_badge

            refresh_current_badge(project, text=badge, disc_root=ROOT)
        run(
            "tools/special_disc/writeback/build_full_text.py",
            "--work-directory",
            "work/build/resource-components",
            *(["--force-rebuild"] if force else []),
        )
        if staged:
            # resource views name their parts relative to themselves: the project moves as it is
            directory.mkdir(parents=True, exist_ok=True)
            final = directory / project.name
            project.rename(final)
            project = final
    finally:
        if holding is not None:
            shutil.rmtree(holding, ignore_errors=True)
    seal = directory / "verified.json"
    path = project / "work/build/resource-components/final.spview"
    view = ResourceView.load(path)
    if input_state(region, badge, component_frontends)[2] != fingerprint:
        raise ValueError("build inputs changed during SP compilation")
    temp = project / "seal.tmp"
    temp.write_text(
        json.dumps({"path": str(path.relative_to(directory)), "sha256": view.digest()})
    )
    temp.replace(seal)
    print(
        f"[{region}] resource compilation {time.monotonic() - started:.2f}s", flush=True
    )
    return view


def prune_resources(region, active):
    """Keep three verified regional workspaces, including the one just published."""
    root = CACHE / region
    verified = sorted(
        root.glob("*/verified.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    retained = {active}
    for seal in verified:
        if seal.parent in retained:
            continue
        if len(retained) < 3:
            retained.add(seal.parent)
        elif len(seal.parent.name) == 64 and all(
            c in "0123456789abcdef" for c in seal.parent.name
        ):
            shutil.rmtree(seal.parent)
    # A forced rebuild of the same signature creates a new immutable workspace.
    # Delete only superseded successful projects, after both disc and receipt are published.
    for directory in retained:
        current = (
            directory / json.loads((directory / "verified.json").read_text())["path"]
        ).parents[3]
        for project in directory.glob("inputs-*"):
            if (
                project != current
                and (project / "work/build/resource-components/final.spview").is_file()
            ):
                shutil.rmtree(project)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--badge")
    parser.add_argument("--component-frontends", action="store_true")
    parser.add_argument(
        "--frontend-receipts", type=Path,
        help="directory of frontend receipts to compile from instead of the Original candidate receipts",
    )
    parser.add_argument(
        "--await-frontends", action="store_true",
        help="with --frontend-receipts: the receipts are still being written; start the regions now",
    )
    parser.add_argument(
        "--compile-only", action="store_true",
        help="compile and seal the three regions' resources; write no disc (the build that follows reuses them)",
    )
    parser.add_argument(
        "--publish-when", type=Path,
        help="compile now, then wait for this file before laying out and publishing the disc; a file of the "
             "same name with .cancel ends the build without a disc (build_multilang.py: the other editions' "
             "builds and checks decide)",
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / "build/iso/test/multilang-sp.iso"
    )
    args = parser.parse_args()
    if args.frontend_receipts:
        args.component_frontends = args.frontend_receipts.resolve()
    os.environ[ENV] = "1"
    start = time.monotonic()
    args.out = args.out.resolve()
    if (
        not args.out.parent.is_relative_to((ROOT / "build/iso/test").resolve())
        or args.out.suffix != ".iso"
    ):
        parser.error("SP output must be an ISO in build/iso/test")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with edition_lock(ROOT / "work/cache/editions/sp-resources.lock"):
        for region in REGIONS:                       # holding directories an interrupted build left behind
            for stale in (CACHE / region).glob(".staging-*"):
                shutil.rmtree(stale, ignore_errors=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [
                pool.submit(compile_region, region, args.force_rebuild, args.badge,
                            args.component_frontends, args.await_frontends)
                for region in REGIONS
            ]
            results, unavailable = [], None
            for job in jobs:                         # every region ends before anything is reported
                try:
                    results.append(job.result())
                except FrontendsUnavailable as error:
                    unavailable = error
            if unavailable is not None:
                print(f"SP resources not compiled: {unavailable}", flush=True)
                raise SystemExit(3)
            sc, tw, hk = results
        if args.compile_only:
            print(f"SP resources compiled {time.monotonic() - start:.2f}s", flush=True)
            return
        if args.publish_when:
            print(f"SP resources compiled {time.monotonic() - start:.2f}s", flush=True)
            cancel = args.publish_when.with_name(args.publish_when.name + ".cancel")
            while not args.publish_when.exists():
                if cancel.exists():
                    print("SP disc not written: the build was cancelled", flush=True)
                    raise SystemExit(4)
                time.sleep(0.1)
        with tempfile.TemporaryDirectory(dir=args.out.parent) as temp:
            staged = Path(temp) / "final.iso"
            receipt = Path(temp) / "verified.json"
            a = SimpleNamespace(
                edition="sp",
                sc=sc,
                tc=tw,
                hk=hk,
                out=args.out,
                work=ROOT / "build/multilang/assemble-sp",
                codebook=ROOT / "config/encoding/zh-release-font-assignments.json",
                tc_codebook=ROOT
                / "config/zh-hant/encoding/zh-release-font-assignments.json",
            )
            layout_start = time.monotonic()
            assemble_dual.assemble(a, staged, receipt)
            report = json.loads(receipt.read_text())
            report["resources"] = {
                region: str(view.path.relative_to(ROOT))
                for region, view in zip(REGIONS, (sc, tw, hk))
            }
            report["source"] = "Japanese retail SP"
            receipt.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
            with ThreadPoolExecutor(max_workers=3) as pool:
                current = pool.map(
                    lambda region: input_state(
                        region, args.badge, args.component_frontends
                    )[2],
                    REGIONS,
                )
                if list(current) != [
                    view.path.parents[4].name for view in (sc, tw, hk)
                ]:
                    raise ValueError("SP inputs changed before publication")
            assemble_dual.publish(
                staged, args.out, receipt, args.out.with_suffix(".receipt.json")
            )
            print(
                f"[sp-layout] write, verify and publish {time.monotonic() - layout_start:.2f}s",
                flush=True,
            )
        for region, view in zip(REGIONS, (sc, tw, hk)):
            try:
                prune_resources(region, view.path.parents[4])
            except (OSError, ValueError, KeyError) as error:
                print(
                    f"[{region}] resource cache cleanup skipped: {error}",
                    file=sys.stderr,
                )
    print(f"SP full resource build {time.monotonic() - start:.2f}s", flush=True)


if __name__ == "__main__":
    main()
