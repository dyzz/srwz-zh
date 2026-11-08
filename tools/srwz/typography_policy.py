"""Explicit project-local typography policy for isolated candidate builds.

Absence means native production behavior. A candidate snapshot opts in via
config/text-layout/rendering-mode.json; no environment or global monkeypatch.
"""
from functools import lru_cache
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
def load_policy(root=ROOT):
 p=Path(root)/'config/text-layout/rendering-mode.json'
 if not p.exists():return {'mode':'native','chinese_punctuation':'native'}
 d=json.loads(p.read_text())
 if d=={'mode':'native'}:return {'mode':'native','chinese_punctuation':'native'}
 if d not in ({'mode':'proportional','chinese_punctuation':'compact'},
              {'mode':'proportional','chinese_punctuation':'compact','candidate_only':True}):
  raise ValueError('Unsupported rendering-mode policy')
 return {'mode':'proportional','chinese_punctuation':'compact'}

@lru_cache(maxsize=1)
def candidate_enabled():
 return load_policy()['mode']=='proportional'

def options(typography=None,chinese_punctuation=None):
 enabled=candidate_enabled()
 return (typography if typography is not None else 'proportional' if enabled else 'native',
         chinese_punctuation if chinese_punctuation is not None else 'compact' if enabled else 'native')
