"""Real locked-source link ownership must win over translated punctuation."""
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/text_layout'))
from build_tag_free_candidate import migration_request

class SourceOwnerTests(unittest.TestCase):
 def test_plain_book_title_and_runtime_link_are_distinguished(self):
  proof=json.loads((ROOT/'tests/fixtures/tag-free-source-owners.json').read_text())
  owners=dict(entries={c['entry']['id']:c['owner'] for c in proof['cases']})
  results=[migration_request(c['entry'],owners)for c in proof['cases']]
  self.assertTrue(all('《'in r['text'] for r in results))
  self.assertTrue(all(r['options']['chinesePunctuation']=='compact' for r in results))
  self.assertEqual([r['options']['keywordLinks']for r in results],[True,False])
 def test_missing_or_changed_source_binding_is_rejected(self):
  proof=json.loads((ROOT/'tests/fixtures/tag-free-source-owners.json').read_text());case=proof['cases'][0]
  with self.assertRaisesRegex(ValueError,'Source binding mismatch'):migration_request(case['entry'],dict(entries={}))
  owners=dict(entries={case['entry']['id']:{**case['owner'],'sourceTextSha256':'0'*64}})
  with self.assertRaisesRegex(ValueError,'Source binding mismatch'):migration_request(case['entry'],owners)
