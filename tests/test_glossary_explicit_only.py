import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.glossary import load_global_glossary, relevant_glossary_terms


class ExplicitOnlyGlossaryTests(unittest.TestCase):
    def test_contextual_translation_requires_explicit_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "terms.json").write_text(
                json.dumps(
                    {
                        "terms": [
                            {
                                "id": "technology/photon-mat",
                                "source_terms": ["フォトンマット"],
                                "translation": "光子垫",
                                "status": "approved",
                                "enforce": True,
                            },
                            {
                                "id": "weapon/photon-mat",
                                "source_terms": ["フォトンマット"],
                                "translation": "光子垫攻击",
                                "registry_match": "explicit_only",
                                "status": "approved",
                                "enforce": False,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            terms = load_global_glossary(root)
            matched = relevant_glossary_terms("フォトンマット", terms)

        self.assertEqual([item["id"] for item in matched], ["technology/photon-mat"])
        weapon = next(item for item in terms if item["id"] == "weapon/photon-mat")
        self.assertEqual(weapon["translation"], "光子垫攻击")
        self.assertEqual(weapon["registry_match"], "explicit_only")


if __name__ == "__main__":
    unittest.main()
