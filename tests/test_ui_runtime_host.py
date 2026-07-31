import tempfile
import unittest
from pathlib import Path

from tools.srwz.ui_runtime_host import build_runtime_host_preflight


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = PROJECT_ROOT / "config/runtime/ui-test-matrix.json"


class UiRuntimeHostTests(unittest.TestCase):
    def _report(
        self,
        *,
        binary_architectures,
        has_rosetta,
        artifact_id="first-five-full-ui-with-compdata",
    ):
        with tempfile.TemporaryDirectory() as directory:
            pcsx2 = Path(directory) / "PCSX2"
            pcsx2.write_bytes(b"fake executable")
            pcsx2.chmod(0o755)
            return build_runtime_host_preflight(
                PROJECT_ROOT,
                MATRIX_PATH,
                pcsx2,
                host_architecture="arm64",
                binary_architectures=binary_architectures,
                has_rosetta=has_rosetta,
                pine_socket_path=Path(directory) / "pcsx2.sock",
                artifact_id=artifact_id,
            )

    def test_x86_binary_without_rosetta_fails_closed(self):
        report = self._report(
            binary_architectures=("x86_64",),
            has_rosetta=False,
        )
        self.assertEqual(report["status"], "runtime_host_blocked")
        self.assertFalse(report["launch"]["safe_to_launch"])
        self.assertEqual(report["launch"]["blockers"], ["rosetta_missing"])
        self.assertEqual(report["runtime"]["status"], "not_tested")

    def test_rosetta_unblocks_the_locked_x86_runtime(self):
        report = self._report(
            binary_architectures=("x86_64",),
            has_rosetta=True,
        )
        self.assertEqual(report["status"], "runtime_host_ready")
        self.assertTrue(report["launch"]["safe_to_launch"])
        self.assertEqual(report["launch"]["blockers"], [])

    def test_ready_cases_and_integrated_iso_are_exact(self):
        report = self._report(
            binary_architectures=("x86_64",),
            has_rosetta=False,
        )
        self.assertEqual(report["ready_cases"]["count"], 5)
        self.assertEqual(
            report["ready_cases"]["case_ids"],
            [
                "core/title-main-menu",
                "core/opening-player-setup",
                "core/world-history-scroll",
                "fresh-boot/tutorial-unit-stat-terrain",
                "first-five/stage-001-opening",
            ],
        )
        self.assertEqual(
            report["artifact"]["iso_sha256"],
            "218de6c432fd0d076cc464b68a8868349ced4f585e31608b8c4b0f49e4dff63b",
        )

    def test_p2_default_name_artifact_can_be_selected_exactly(self):
        report = self._report(
            binary_architectures=("x86_64",),
            has_rosetta=True,
            artifact_id="ui-p2-default-names-first-five",
        )
        self.assertEqual(report["ready_cases"]["count"], 1)
        self.assertEqual(
            report["ready_cases"]["case_ids"],
            ["fresh-boot/default-protagonist-labels"],
        )
        self.assertEqual(
            report["artifact"]["iso_sha256"],
            "026f29e3e77b78a19f000c6781317ebc95aeb672b5b2848ad2a30bf8d2f5c473",
        )

    def test_wrong_binary_architecture_is_reported(self):
        report = self._report(
            binary_architectures=("arm64",),
            has_rosetta=True,
        )
        self.assertEqual(
            report["launch"]["blockers"],
            ["pcsx2_architecture_mismatch"],
        )


if __name__ == "__main__":
    unittest.main()
