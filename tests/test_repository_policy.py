import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED_ROOTS = (
    "build/",
    "font/generated/",
    "outputs/",
    "rom/",
    "work/",
)
FORBIDDEN_DISC_SUFFIXES = {
    ".chd",
    ".iso",
    ".p2s",
    ".ps2",
    ".sav",
}
FORBIDDEN_HELPER_NAMES = {
    "CompressTool.exe",
    "SRWZ.dll",
    "SRWZ.exe",
}
MAX_TRACKED_FILE_SIZE = 10 * 1024 * 1024


def tracked_paths() -> tuple[Path, ...]:
    result = subprocess.run(
        ("git", "ls-files", "-z"),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw)


class RepositoryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PROJECT_ROOT / ".git").exists():
            raise unittest.SkipTest("repository policy needs Git metadata")
        cls.paths = tracked_paths()

    def test_private_and_generated_roots_are_not_tracked(self):
        offenders = [
            path.as_posix()
            for path in self.paths
            if path.as_posix().startswith(FORBIDDEN_TRACKED_ROOTS)
        ]
        self.assertEqual(offenders, [])

    def test_disc_images_saves_and_windows_helpers_are_not_tracked(self):
        offenders = [
            path.as_posix()
            for path in self.paths
            if path.suffix.lower() in FORBIDDEN_DISC_SUFFIXES
            or path.name in FORBIDDEN_HELPER_NAMES
        ]
        self.assertEqual(offenders, [])

    def test_tracked_files_stay_reviewable(self):
        offenders = [
            f"{path.as_posix()} ({(PROJECT_ROOT / path).stat().st_size})"
            for path in self.paths
            if (PROJECT_ROOT / path).is_file()
            and (PROJECT_ROOT / path).stat().st_size > MAX_TRACKED_FILE_SIZE
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
