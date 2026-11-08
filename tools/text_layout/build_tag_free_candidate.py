"""Create an isolated tag-free story projection, without writing source/ISO.

Every rejected owner is retained in the receipt; no legacy-width fallback.
This is a text-component preflight, not an executable/ISO promotion command.
"""
from pathlib import Path
import argparse, hashlib, json, re, sys, shutil
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from srwz.js_layout import layout_batch
import srwz.js_layout as js_layout
from srwz.build_layout import runtime_inputs,RUNTIME_FILES

def migration_request(entry,owners):
    owner=owners['entries'].get(entry['id'])
    if owner is None or owner['sourceTextSha256']!=entry['source_text_sha256']:
        raise ValueError(f"Source binding mismatch: {entry['id']}")
    text=entry['translation'];visible=re.sub(r'</?z>','',text)
    structured=visible.startswith((' ','　')) or bool(re.search(r'”\n[　 ]*“',visible))
    return dict(action='measure' if structured else 'layout',scene='story',text=text,options=dict(typography='proportional',chinesePunctuation='compact',keywordLinks=owner['keywordLinks']))

def build(stages,output,source_index):
    source_index=source_index.resolve()
    source_index_bytes=source_index.read_bytes()
    owners=json.loads(source_index_bytes)
    from rebalance_story_dialogue import DEFAULT_CONFIG
    if owners["configSha256"]!=hashlib.sha256(DEFAULT_CONFIG.read_bytes()).hexdigest():
        raise ValueError("Source owner configuration changed; regenerate source index")
    output=output.resolve()
    if output==ROOT or ROOT/'corpus' in output.parents or output==ROOT/'corpus':
        raise ValueError('Candidate output must not replace source corpus')
    output.mkdir(parents=True,exist_ok=True)
    inputs=runtime_inputs()
    runtime=output/'runtime';runtime.mkdir(exist_ok=True)
    for name in RUNTIME_FILES:shutil.copyfile(ROOT/'shared/text-layout'/name,runtime/name)
    # Every batch executes the same frozen runtime, even if development continues.
    js_layout.CLI=runtime/'cli.mjs'
    for value in inputs.values():
        snapshot=runtime/Path(value['path']).name
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest()==value['sha256']
    (output/'receipt.json').write_text(json.dumps(dict(complete=False,status='running',inputs=inputs),indent=2)+'\n')
    paths=sorted((ROOT/'corpus/zh/story-dialogue').glob('stage-*.json'))
    if stages:paths=[p for p in paths if int(p.stem.split('-')[1]) in stages]
    if not paths:raise ValueError('No matching stage corpora')
    receipt=dict(kind='isolated tag-free source projection; no runtime or ISO claim',typography='proportional',chinesePunctuation='compact',sourceOwnerIndexSha256=hashlib.sha256(source_index_bytes).hexdigest(),keywordOwnershipVerified=True,inputs=inputs,files=[],passed=0,rejected=0)
    for path in paths:
        source=json.loads(path.read_text());entries=source['entries'];projected=json.loads(json.dumps(source));records=[]
        requests=[migration_request(entry,owners) for entry in entries]
        for start in range(0,len(requests),64):
            responses=layout_batch(requests[start:start+64],timeout=120)
            for index,response in enumerate(responses,start):
                entry=entries[index];request=requests[index]
                if response['ok']:
                    result=response['result']
                    text=result.get('compiledText') if request['action']=='layout' else '\n'.join(row['text']for row in result['rows'])
                    if len(result['rows'])>3 or any(row['occupiedPx']>483 for row in result['rows']):
                        response=dict(ok=False,error=dict(code='owner_geometry',message='Structured owner exceeds dialogue geometry'))
                    elif '<z>'in text or '</z>'in text:
                        raise AssertionError('Tag-free request returned compact markup')
                    else:
                        projected['entries'][index]['translation']=text
                        records.append(dict(id=entry['id'],status='passed',action=request['action'],needsRuntimeAlignment=request['action']=='measure',changed=text!=entry['translation'],rowWidths=[r['occupiedPx']for r in result['rows']]))
                        receipt['passed']+=1
                if not response['ok']:
                    # Never present the rejected original entry as migrated.
                    projected['entries'][index]['tag_free_error']=response['error']
                    records.append(dict(id=entry['id'],status='rejected',error=response['error']))
                    receipt['rejected']+=1
        destination=output/'corpus/zh/story-dialogue'/path.name;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(projected,ensure_ascii=False,indent=2)+'\n')
        receipt['files'].append(dict(source=str(path.relative_to(ROOT)),sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),candidate=str(destination.relative_to(output)),candidateSha256=hashlib.sha256(destination.read_bytes()).hexdigest(),records=records))
        print(path.name, len(records), 'checked',flush=True)
    receipt['complete']=receipt['rejected']==0
    (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:receipt[k]for k in ['passed','rejected','complete']}))
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',action='append',type=int);p.add_argument('--output',type=Path,required=True);p.add_argument('--source-index',type=Path,required=True);args=p.parse_args()
    build(set(args.stage or []),args.output,args.source_index)
