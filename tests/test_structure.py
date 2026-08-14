import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "argparse",
    "array",
    "audit_source_bound_glossary",
    "audit_stage_keyword_links",
    "base64",
    "bisect",
    "binascii",
    "build_library_v02_component",
    "build_story_component",
    "collections",
    "concurrent",
    "configparser",
    "copy",
    "csv",
    "dataclasses",
    "functools",
    "hashlib",
    "html",
    "io",
    "itertools",
    "json",
    "math",
    "os",
    "pathlib",
    "platform",
    "plistlib",
    "re",
    "run_aliyun_library_v02_batch",
    "run_library_v02_full_editorial_audit",
    "signal",
    "shutil",
    "socket",
    "srwz",
    "statistics",
    "string",
    "struct",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "tools",
    "types",
    "typing",
    "urllib",
    "unicodedata",
    "verify_full_story_iso_content",
    "xml",
    "zipfile",
    "zlib",
}


class SourceStructureTests(unittest.TestCase):
    def test_production_tools_do_not_import_editorial_review_builder(self):
        forbidden = "build_editorial_review"
        for path in sorted(TOOLS_ROOT.rglob("*.py")):
            if path.name == "build_editorial_review.py":
                continue
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                tree = ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                )
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
                self.assertFalse(
                    any(forbidden in name for name in imports),
                    f"production tool imports manual review builder: {path}",
                )

    def test_project_python_uses_only_stdlib_and_local_imports(self):
        for path in sorted(TOOLS_ROOT.rglob("*.py")):
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                tree = ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                )
                roots = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        roots.update(
                            alias.name.partition(".")[0] for alias in node.names
                        )
                    elif (
                        isinstance(node, ast.ImportFrom)
                        and node.level == 0
                        and node.module
                    ):
                        roots.add(node.module.partition(".")[0])
                self.assertEqual(
                    roots - ALLOWED_IMPORT_ROOTS,
                    set(),
                    f"undeclared Python dependency in {path}",
                )

    def test_clean_room_core_has_no_absolute_project_imports(self):
        for path in sorted((TOOLS_ROOT / "srwz").glob("*.py")):
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                tree = ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                )
                absolute_project_imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        absolute_project_imports.extend(
                            alias.name
                            for alias in node.names
                            if alias.name.partition(".")[0]
                            in {"srwz", "tools", "vendor"}
                        )
                    elif (
                        isinstance(node, ast.ImportFrom)
                        and node.level == 0
                        and node.module
                        and node.module.partition(".")[0] in {"srwz", "tools", "vendor"}
                    ):
                        absolute_project_imports.append(node.module)
                self.assertEqual(absolute_project_imports, [])


if __name__ == "__main__":
    unittest.main()
