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
from build_dual_sp import taiwan_data_link_literals

REGIONS = ("sc", "tw", "hk")
CACHE = ROOT / "work/build/sp-multilang-resources"


def input_state(region, badge, component_frontends):
    language = "" if region == "sc" else "zh-hant-" + region
    rows = source_inventory(ROOT, locked_sp_inputs(ROOT), language=language)

    def frontend(r):
        lang = "" if r == "sc" else "zh-hant-" + r
        if not component_frontends:
            return _answer_key(ROOT, lang, True)
        receipt = json.loads(
            (ROOT / f"work/cache/editions/sp-frontends/{lang or 'zh'}.json").read_text()
        )
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
        # HK compiles its own battle lines. Taiwan can still supply a shared
        # Data Link literal via the bilingual dictionary, so bind those exact values.
        keyed_rows = [row for row in rows if row["path"] != taiwan_subtitles]
        external["taiwan_data_link"] = taiwan_data_link_literals()
    fingerprint = hashlib.sha256(
        json.dumps([keyed_rows, external, badge], sort_keys=True).encode()
    ).hexdigest()
    return rows, keys, fingerprint


def compile_region(region, force, badge, component_frontends):
    started = time.monotonic()
    rows, keys, fingerprint = input_state(region, badge, component_frontends)
    directory = CACHE / region / fingerprint
    seal = directory / "verified.json"
    if seal.exists() and not force:
        try:
            doc = json.loads(seal.read_text())
            view = ResourceView.load(directory / doc["path"])
            matches = view.digest() == doc["sha256"]
        except (OSError, ValueError, KeyError):
            matches = False
        if matches:
            seal.touch()
            print(
                f"[{region}] verified resources reused {time.monotonic() - started:.2f}s",
                flush=True,
            )
            return view
    directory.mkdir(parents=True, exist_ok=True)
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

    def run(*args):
        with log.open("a") as out:
            if subprocess.run(
                [sys.executable, *map(str, args)],
                cwd=project,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
            ).returncode:
                raise RuntimeError(f"{region}: {log}\n{log.read_text()[-2500:]}")

    if region != "sc":
        run(
            ROOT / "tools/zh_hant/language_view.py",
            project,
            "--variant",
            region,
            "--editions",
            "sp",
            "--answer-key",
            keys[region],
            "--taiwan-answer-key",
            keys["tw"],
            "--simplified-answer-key",
            keys["sc"],
        )
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
        "--out", type=Path, default=ROOT / "build/iso/test/multilang-sp.iso"
    )
    args = parser.parse_args()
    os.environ[ENV] = "1"
    start = time.monotonic()
    args.out = args.out.resolve()
    if (
        args.out.parent != (ROOT / "build/iso/test").resolve()
        or args.out.suffix != ".iso"
    ):
        parser.error("SP output must be an ISO in build/iso/test")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with edition_lock(ROOT / "work/cache/editions/sp-resources.lock"):
        with ThreadPoolExecutor(max_workers=3) as pool:
            sc, tw, hk = pool.map(
                lambda region: compile_region(
                    region, args.force_rebuild, args.badge, args.component_frontends
                ),
                REGIONS,
            )
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
