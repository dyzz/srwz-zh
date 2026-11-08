"""Bind tag-free migration to locked Japanese source owners, not punctuation guesses."""
from pathlib import Path
import argparse,hashlib,json
from rebalance_story_dialogue import source_dialogue_index,DEFAULT_CONFIG
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
index=source_dialogue_index()
result=dict(kind='locked Japanese STAGE source owner index',configSha256=hashlib.sha256(DEFAULT_CONFIG.read_bytes()).hexdigest(),entries={identity:dict(keywordLinks=meta['keyword_links'],sourceTextSha256=hashlib.sha256(meta['text'].encode('utf-8')).hexdigest())for identity,meta in index.items()})
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
print('Source ownership indexed:',len(index),flush=True)
