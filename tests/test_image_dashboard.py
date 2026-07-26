import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.build_image_dashboard import (
    ImageDashboardCliError,
    build_dashboard,
    require_output_path,
)
from tools.srwz.image_dashboard import (
    ImageDashboardError,
    build_dashboard_payload,
    render_dashboard_html,
)


FIELDS = [
    "member",
    "chunk_index",
    "view",
    "stored_start",
    "record_index",
    "record_offset",
    "record_size",
    "record_sha256",
    "picture_index",
    "width",
    "height",
    "bits_per_pixel",
    "clut_color_count",
    "uses_shared_clut",
    "tim2_path",
    "png_path",
    "render_status",
    "palette_source_picture_index",
    "palette_bank_index",
    "palette_bank_count",
    "png_sha256",
    "render_error",
]


def make_manifest(picture_count=2, member_count=1):
    return {
        "scope": "test export",
        "completion_status": "complete",
        "totals": {
            "picture_count": picture_count,
            "tim2_record_count": 1,
            "members_with_valid_tim2": member_count,
            "payload_count": 1,
            "available_palette_bank_view_count": 4,
            "render_failure_count": 0,
        },
    }


def make_rows():
    base = {
        "member": "BTL/TWP.BIN",
        "chunk_index": "3",
        "view": "decoded",
        "stored_start": "64",
        "record_index": "0",
        "record_offset": "32",
        "record_size": "256",
        "record_sha256": "a" * 64,
        "picture_index": "0",
        "width": "32",
        "height": "16",
        "bits_per_pixel": "4",
        "clut_color_count": "32",
        "uses_shared_clut": "False",
        "tim2_path": "by-member/BTL/TWP.BIN/a/record.tm2",
        "png_path": "by-member/BTL/TWP.BIN/a/picture-000.png",
        "render_status": "rendered",
        "palette_source_picture_index": "0",
        "palette_bank_index": "0",
        "palette_bank_count": "2",
        "png_sha256": "b" * 64,
        "render_error": "",
    }
    second = dict(base)
    second["picture_index"] = "1"
    second["png_path"] = "by-member/BTL/TWP.BIN/a/picture-001.png"
    return [base, second]


class ImageDashboardTests(unittest.TestCase):
    def test_builds_payload_and_marks_duplicate_pngs(self):
        payload = build_dashboard_payload(make_manifest(), make_rows())

        self.assertEqual(payload["meta"]["totals"]["uniquePngs"], 1)
        self.assertEqual(payload["meta"]["totals"]["duplicateRows"], 1)
        self.assertEqual(payload["images"][0]["duplicateCount"], 2)
        self.assertTrue(payload["images"][0]["primary"])
        self.assertFalse(payload["images"][1]["primary"])
        self.assertEqual(payload["members"][0]["pictures"], 2)

    def test_renders_self_contained_local_html(self):
        html = render_dashboard_html(make_manifest(), make_rows())

        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("SRWZ 图片资源总览", html)
        self.assertIn("by-member/BTL/TWP.BIN/a/picture-000.png", html)
        self.assertNotIn("__DASHBOARD_DATA__", html)
        self.assertNotIn("fetch(", html)

        marker = '<script type="application/json" id="dashboardData">'
        encoded = html.split(marker, 1)[1].split("</script>", 1)[0]
        payload = json.loads(encoded)
        self.assertEqual(len(payload["images"]), 2)

    def test_rejects_picture_count_mismatch(self):
        with self.assertRaisesRegex(ImageDashboardError, "picture_count"):
            build_dashboard_payload(make_manifest(picture_count=3), make_rows())

    def test_rejects_output_outside_export_root(self):
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name) / "export"
            root.mkdir()

            with self.assertRaisesRegex(
                ImageDashboardCliError,
                "must stay",
            ):
                require_output_path(root, Path(temporary_name) / "index.html")

    def test_cli_builds_index_inside_export(self):
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name) / "export"
            (root / "by-member").mkdir(parents=True)
            (root / "manifest.json").write_text(
                json.dumps(make_manifest()),
                encoding="utf-8",
            )
            with (root / "images.csv").open(
                "w",
                newline="",
                encoding="utf-8",
            ) as target:
                writer = csv.DictWriter(target, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(make_rows())

            report = build_dashboard(
                root,
                root / "index.html",
                force=False,
            )

            self.assertEqual(report["picture_count"], 2)
            self.assertTrue((root / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
