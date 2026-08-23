import hashlib
import json
from pathlib import Path

from tools.srwz.mtv_prop_intertitles import build_mtv_prop_intertitles
from tools.srwz.text import decode_text, encode_text, load_text_table


ROOT = Path(__file__).resolve().parents[1]


def test_issue_011_mtv_prop_intertitles_cover_complete_archive():
    contract = json.loads(
        (ROOT / "corpus/zh/chapter-intertitles.json").read_text(
            encoding="utf-8"
        )
    )
    output, report = build_mtv_prop_intertitles(
        (ROOT / "work/disc/DATA/MTV_PROP.BIN").read_bytes(),
        (ROOT / "work/disc/SLPS_258.87").read_bytes(),
        ROOT
        / "work/font-source/harmonyos-sans-sc-1.0/"
        "HarmonyOS_Sans_SC_Regular.ttf",
        contract,
    )
    assert len(output) == 2_232_448
    assert hashlib.sha256(output).hexdigest() == contract[
        "output_archive_sha256"
    ]
    assert report["chunk_count"] == 23
    assert report["tim2_chunk_count"] == 23
    assert report["localized_chunk_indices"] == [21, 22]
    assert report["unchanged_chunk_count"] == 21
    assert report["non_target_chunks_preserved_byte_exact"] is True
    assert report["translated_reread_exact"] is True


def test_issue_022_auto_squad_root_table_is_complete_and_reviewed():
    source = (ROOT / "work/disc/SLPS_258.87").read_bytes()
    table = load_text_table(
        ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    remaining = json.loads(
        (ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
            encoding="utf-8"
        )
    )["slps_by_offset"]
    expected = [
        ("キング・ビアル", "帝皇比亚路"),
        ("アーガマ", "阿伽玛"),
        ("アイアン・ギアー", "钢铁齿轮"),
        ("アイアン・ギアー", "钢铁齿轮"),
        ("グローマ", "格罗玛"),
        ("フリーデン", "和平号"),
        ("月光号", "月光号"),
        ("アークエンジェル", "大天使"),
        ("ミネルバ", "密涅瓦"),
        ("ソレイユ", "太阳号"),
        ("エターナル", "永恒"),
        ("エターナル", "永恒"),
        ("ラーディッシュ", "拉迪修"),
    ]
    assert len(expected) == 13
    for index, (source_text, translation) in enumerate(expected):
        offset = 0x31B610 + index * 0x14
        decoded = decode_text(source, offset, table, end=offset + 0x14)
        assert decoded.text == source_text
        assert not any(source[decoded.end : offset + 0x14])
        assert remaining[f"0x{offset:X}"] == translation


def test_issue_054_remaining_squad_count_keeps_raw_printf_width_token():
    source = (ROOT / "work/disc/SLPS_258.87").read_bytes()
    table = load_text_table(
        ROOT / "vendor/upstream-python/project/tbl_all.json"
    )
    remaining = json.loads(
        (ROOT / "corpus/zh/menu/remaining-ui.json").read_text(
            encoding="utf-8"
        )
    )["slps_context_ui_by_offset"]
    decoded = decode_text(source, 0x33FC80, table)
    assert decoded.text == "%<width:64>隊"
    assert remaining["0x33FC80"] == "%<width:64>"
    assert encode_text(
        remaining["0x33FC80"],
        table,
        overrides={"%": 0x9865, "2": 0x8140, "d": 0x8141},
        terminate=True,
    ) == b"%2d\x00"


def test_issue_016_020_026_stage_component_has_structural_closure():
    report = json.loads(
        (
            ROOT
            / "work/build/full-story-stage/components/"
            "component-validation.json"
        ).read_text(encoding="utf-8")
    )
    assert report["story_ticker_count"] == 89
    assert report["story_ticker_source_count"] == 46
    assert report["story_ticker_stage_count"] == 89
    assert report["story_ticker_structural_slots_exact"] is True
    assert report["story_ticker_translated_reread_exact"] is True
    assert report["z_report_count"] == 2
    assert report["z_report_source_count"] == 2
    assert report["z_report_stage_indices"] == [36]
    assert report["z_report_inventory_sha256"] == (
        "88dc3b72d46b201d7949e0e441ceb60fc9eca1893e63f335bd36cba9c3a1acd9"
    )
    assert report["z_report_structural_slots_exact"] is True
    assert report["z_report_fixed_slots_exact"] is True
    assert report["z_report_translated_reread_exact"] is True
    assert report["tutorial_binding"] == {
        "stage_names": {"185": "stg_500.bin", "186": "stg_501.bin"},
        "dialogue_counts": {"185": 407, "186": 431},
        "total_dialogue_count": 838,
        "source_stage_headers_exact": True,
        "translated_stage_reread_exact": True,
        "alternate_mtv_prop_text_owner_ruled_out": True,
    }
