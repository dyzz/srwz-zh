"""Regression for route twins hidden by unrelated uses of one Japanese line."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/editorial_review"))

from unify_same_source_dialogue import (  # noqa: E402
    load_corpus,
    scene_components,
    source_dialogue_index,
    source_stage_ordinals,
)


class SameSourceSceneTest(unittest.TestCase):
    def test_route_twins_are_found_even_when_source_repeats_elsewhere(self) -> None:
        source = source_dialogue_index()
        ordinals = {
            stage: meta["stage_ordinal"]
            for stage, meta in source_stage_ordinals(source).items()
        }
        component_of = {
            entry["id"]: frozenset(member["id"] for member in component)
            for component in scene_components(load_corpus(), source, ordinals)
            for entry in component
        }
        pair = frozenset({
            "story/136/dialogue/01.118/0003",
            "story/139/dialogue/01.135/0003",
        })
        self.assertEqual(component_of["story/136/dialogue/01.118/0003"], pair)
        self.assertNotIn("story/136/dialogue/01.116/0003", component_of["story/136/dialogue/01.118/0003"])
        self.assertFalse(any(entry_id.startswith("story/185/") for entry_id in component_of))


if __name__ == "__main__":
    unittest.main()
