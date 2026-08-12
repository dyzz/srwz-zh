import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProductionDecoderPolicyTests(unittest.TestCase):
    def test_tools_do_not_import_python_resource_decoder(self):
        violations = []
        for path in sorted((PROJECT_ROOT / "tools").rglob("*.py")):
            if path == PROJECT_ROOT / "tools/srwz/codec.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module not in {
                    "srwz.codec",
                    "tools.srwz.codec",
                    "codec",
                }:
                    continue
                if any(alias.name == "decode" for alias in node.names):
                    violations.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
