import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.srwz.library import apply_source_surface_replacements


ROOT = Path(__file__).resolve().parents[1]


class LibrarySourceBoundVariantTests(unittest.TestCase):
    def test_library_apply_skips_terms_outside_library_domain(self) -> None:
        source_row = {
            "id": "library-text/domain-filter",
            "source_text_sha256": "domain-filter",
            "model_source_text": "その大いなる力を発揮した。",
        }
        corpus = {
            "entries": [
                {
                    "id": source_row["id"],
                    "source_text_sha256": source_row["source_text_sha256"],
                    "translation": "发挥了强大力量。",
                    "glossary_refs": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "source.jsonl"
            reviewed = directory / "reviewed.json"
            report = directory / "report.json"
            source.write_text(
                json.dumps(source_row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            reviewed.write_text(
                json.dumps(corpus, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        ROOT
                        / "tools/apply_library_source_bound_glossary_variants.py"
                    ),
                    "--term-id",
                    "concept/great-power",
                    "--source",
                    str(source),
                    "--corpus",
                    str(reviewed),
                    "--report",
                    str(report),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "tools")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(document["matched_entry_count"], 0)
        self.assertEqual(document["changed_entry_count"], 0)
        self.assertEqual(document["unresolved_count"], 0)

    def test_sirius_fallen_angel_title_does_not_duplicate_the_name(self) -> None:
        config = json.loads(
            (ROOT / "config/editorial/library-polish.json").read_text(
                encoding="utf-8"
            )
        )
        for before in (
            "诗翅西里乌斯",
            "诗翅西利乌斯",
            "诗翅<西里乌斯>",
            "诗翅<西利乌斯>",
            "诗翅（西里乌斯）",
            "诗翅",
        ):
            with self.subTest(before=before):
                after, applied = apply_source_surface_replacements(
                    before,
                    "詩翅＜シリウス＞",
                    config,
                )
                self.assertEqual(after, "诗翅（西利乌斯）")
                self.assertTrue(applied)

    def test_grandiva_source_surface_keeps_gasshin_grammar(self) -> None:
        config = json.loads(
            (ROOT / "config/editorial/library-polish.json").read_text(
                encoding="utf-8"
            )
        )
        after, applied = apply_source_surface_replacements(
            "与格兰迪瓦组合神后完成",
            "グランディーヴァが合神することで完成する",
            config,
        )
        self.assertEqual(after, "与超重机组合神后完成")
        self.assertTrue(applied)

    def test_reviewed_library_uses_current_source_bound_terms(self) -> None:
        term_ids = [
            "activity/lifting",
            "ability/overskill",
            "event/exodus",
            "organization/london-ima",
            "organization/saint-regan",
            "organization/siberian-railway",
            "organization/siberian-railway-full",
            "organization/siberian-railway-guard",
            "organization/siberian-railway-guard-short",
            "people/speaker-22359c86b24b",
            "system/hangar",
            "technology/photon-mat",
            "technology/photon-mat-ring",
            "organization/deava",
            "place/domepolis",
            "place/yapans-ceiling",
            "place/trinity-base",
            "place/atlandia",
            "place/genganam",
            "place/mountain-cycle",
            "place/ingressa",
            "place/urugsk",
            "unit/black-domi",
            "unit/emperanza",
            "unit/gachiko",
            "unit/overdevil",
            "unit/overman",
            "unit/panther",
            "unit/silhouette-engine",
            "unit/silhouette-machine",
            "unit/silhouette-mammoth",
            "weapon/panther-shoot",
            "episode/gravion-12",
            "faction/zeravire",
            "organization/gran-knights",
            "people/speaker-389b01366661",
            "technology/ergo-form-system",
            "technology/ergo-storm",
            "technology/graviton-critical",
            "unit/g-attacker",
            "unit/g-driller",
            "unit/g-shadow",
            "unit/g-striker",
            "unit/geo-calibur",
            "unit/geo-javelin",
            "unit/geo-mirage",
            "unit/geo-stinger",
            "unit/god-gravion",
            "unit/god-sigma-gravion",
            "unit/goma",
            "unit/gran-diva",
            "unit/gran-kaiser",
            "unit/gran-sigma",
            "unit/gran-trooper",
            "unit/gravion-generic",
            "unit/proto-gran-diva",
            "unit/soldier-zeravire",
            "unit/sol-grandiva",
            "unit/sol-gravion",
            "unit/ultimate-gravion",
            "weapon/0566",
            "weapon/0567",
            "weapon/0570",
            "weapon/0571",
            "weapon/0572",
            "weapon/0573",
            "weapon/0575",
            "weapon/0577",
            "weapon/0578",
            "weapon/0580",
            "weapon/0581",
            "weapon/0583",
            "weapon/0584",
            "weapon/0585",
            "weapon/0586",
            "weapon/0588",
            "weapon/graviton-viper",
            "weapon/sol-graviton-arc",
            "people/civilian",
            "people/fatman-big",
            "people/geraba",
            "organization/sand-rat",
            "unit/brockary",
            "unit/iron-gear",
            "unit/iron-gear-ls",
            "unit/iron-gear-wm",
            "unit/walker-gallia",
            "unit/walker-machine",
            "place/paradigm-city",
            "organization/paradigm-corporation",
            "people/schwarzwald-full",
            "people/speaker-3ebfb90dd843",
            "unit/archetype",
            "unit/megadeus",
            "unit/prairie-dog",
            "concept/dominus",
            "people/sara-tyrell",
            "people/tiffa-adill",
            "people/jamil-neate",
            "people/witz-sou",
            "people/roybea-loy",
            "people/kid-salsamille",
            "people/shagia-frost",
            "people/shingo-mori",
            "people/pala-sys",
            "people/lancerow-darwell",
            "people/katokk-alzamille",
            "people/seidel-rasso",
            "people/carris-nautilus",
            "people/lucille-lilliant",
            "people/abel-bauer",
            "unit/gundam-x-divider",
            "unit/gundam-airmaster",
            "unit/gundam-airmaster-burst",
            "unit/gundam-leopard",
            "unit/gundam-leopard-destroy",
            "unit/gundam-virsago-chest-break",
            "unit/daughtress-neo",
            "unit/clouda",
            "unit/bertigo",
            "unit/gundam-double-x-spoken",
            "unit/g-falcon",
            "unit/airmaster-short",
            "unit/leopard-short",
            "unit/virsago-short",
            "unit/ashtaron-hc",
            "unit/gadiel",
            "unit/rick-dias",
            "unit/re-gz",
            "people/fa-yuiry-full",
            "people/reccoa-londe-full",
            "people/four-murasame-full",
            "people/bran-blutarch-full",
            "people/rosamia-badam-full",
            "people/ben-wood-full",
            "people/henken-bekkener-full",
            "people/mouar-pharaoh-full",
            "technology/psycommu",
            "ability/psycho-frame",
            "weapon/0271",
            "people/chan-agi-library",
            "work/chars-counterattack",
            "people/blex-forer-full",
            "people/gady-kinsey-full",
            "unit/force-impulse-gundam",
            "unit/akatsuki-gundam",
            "unit/minerva",
            "unit/girty-lue",
            "unit/core-splendor",
            "people/lunamaria",
            "people/stella-loussier",
            "technology/getter-rays",
            "unit/getter-short",
            "unit/getter-robo",
            "organization/getter-team",
            "maneuver/open-get",
            "unit/get-machines",
            "unit/command-machine",
            "unit/getter-g-dragon-form",
            "unit/getter-g-liger-form",
            "unit/getter-g-poseidon-form",
            "unit/getter-g-dragon-machine",
            "unit/getter-g-liger-machine",
            "unit/getter-g-poseidon-machine",
            "organization/dinosaur-empire",
            "organization/hyakki",
            "people/burai",
            "unit/hyakki-mecha",
            "unit/hyakki-robot",
            "unit/lady-command",
            "people/emperor-goal",
            "people/gattler-supreme-leader",
            "people/supreme-leader-gattler",
            "title/supreme-leader",
            "product/baldios",
            "unit/baldios",
            "unit/pulsar-burn",
            "unit/new-pulsar-burn",
            "unit/mini-pulsar-burn",
            "unit/spirit-gattler",
            "organization/blue-fixer",
            "faction/aldébaran",
            "people/marin",
            "faction/elder",
            "faction/elder-short",
            "organization/elder-army",
            "unit/eldar-battleship",
            "unit/god-sigma",
            "system/trinity-energy",
            "place/trinity-city",
            "people/gagan",
            "people/teral",
            "people/toshiya",
            "people/speaker-b7d1aa88bb0a",
            "people/speaker-2883579e5ff1",
            "people/speaker-674a17f322f9",
            "people/speaker-499d5f2ed87e",
            "weapon/sigma-breast",
            "concept/human-bomb",
            "group/busu-pair",
            "phrase/chiyonishiki-bark",
            "unit/king-bial",
            "unit/bial-short",
            "location/bial-star",
            "phrase/zambot-boost-short",
            "weapon/0133",
            "weapon/0142",
            "weapon/0143",
            "weapon/0137",
            "weapon/zambot-grap",
            "weapon/zambot-cutter",
            "weapon/zambot-cross-slash",
            "work/zambot-three",
            "unit/zambot-three",
            "unit/zambot",
            "work/daitarn-three",
            "unit/daitarn-three",
            "unit/daitarn-short",
            "unit/dai-fighter",
            "unit/dai-tank",
            "species/meganoid",
            "unit/mega-borg",
            "people/banjo-haran-full",
            "people/beautiful-tachibana-full",
            "people/reika-sanjo-full",
            "people/garrison-tokida-full",
            "weapon/0159",
            "weapon/0160",
            "weapon/0161",
            "weapon/0165",
            "weapon/daitarn-zanber",
            "weapon/daitarn-fan",
            "weapon/daitarn-web",
            "work/orguss",
            "unit/orguss",
            "unit/orguss-flyer",
            "unit/orguss-ii",
            "unit/orguss-ii-flyer",
            "unit/moraver",
            "unit/moraver-maaie",
            "unit/moraver-leia",
            "unit/bronco-ii",
            "unit/drifand",
            "unit/ishforn",
            "unit/ishkick",
            "unit/ishkick-commander",
            "unit/ishkick-commander-ii",
            "unit/naikick-athena",
            "unit/naikick-olson",
            "people/olson-d-verne-full",
            "place/orguss-atlanta",
            "technology/great-singularity",
            "technology/singularity",
            "transform/gerwalk",
            "transform/orguroid",
            "civilization/mu",
            "resource/blue-stone",
            "name/nebulaad",
            "work/aquarion",
            "episode/aquarion-10",
            "episode/aquarion-18",
            "unit/mechanical-angel-aquarion",
            "species/wingless-person",
            "species/mythic-beast",
            "energy/prana",
            "unit/cherubim-generic",
            "people/speaker-94781288b465",
            "unit/cherubim-mars",
            "unit/cherubim-iscuron",
            "unit/cherubim-shururukubera",
            "unit/harvest-beast",
            "unit/solar-aquarion",
            "unit/aquarion-mars",
            "unit/aquarion-luna",
            "unit/aquarion-angel",
            "unit/aquarion-alpha",
            "unit/aquarion-omega",
            "unit/aquarion-delta",
            "unit/aquarion",
            "unit/assault-aquarion",
            "unit/mirror-solar-aquarion",
            "unit/mirror-aquarion-mars",
            "unit/mirror-aquarion-luna",
            "unit/cherubim-verulzeva",
            "unit/grave-cherubim",
            "unit/shibalba",
            "part/vector-machine",
            "part/vector-sol",
            "part/vector-mars",
            "part/vector-luna",
            "part/vector-delta",
            "part/vector-alpha",
            "part/vector-omega",
            "people/speaker-66a2dbb4f5b6",
            "people/sirius-de-alisia",
            "people/silvia-de-alisia",
            "concept/wings-of-sun",
            "concept/tree-of-life",
            "maneuver/genesis-union",
            "item/book-of-genesis",
            "energy/mythic-power",
            "place/element-school",
            "role/first-team-element",
            "ability/element",
            "place/alicia",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "library-source-bound.json"
            command = [
                sys.executable,
                str(ROOT / "tools/apply_library_source_bound_glossary_variants.py"),
                "--report",
                str(report),
                "--fail-on-unresolved",
            ]
            for term_id in term_ids:
                command.extend(("--term-id", term_id))
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "tools")
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = json.loads(report.read_text(encoding="utf-8"))

        self.assertGreater(document["matched_entry_count"], 0)
        self.assertEqual(document["changed_entry_count"], 0)
        self.assertEqual(document["unresolved_count"], 0)


if __name__ == "__main__":
    unittest.main()
