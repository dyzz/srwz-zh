import json,re,subprocess,collections,os,hashlib,pathlib
S=os.path.dirname(os.path.abspath(__file__))
g=lambda r:json.loads(subprocess.check_output(['git','show',r+':corpus/zh/battle/srvc-lines.json']))
old={e['id']:e['translation'] for e in g('756a5ac0^')['entries']}
heads={e['id']:e['translation'] for e in g('HEAD')['entries']}
C=json.load(open(S+'/classes.json'));kind={i:k for k,v in C.items() for i in v}
logical=lambda t:re.sub(r'\\n[　 ]*','',t)
final={};cnt=collections.Counter()
for i,t in heads.items():
    f=t
    if i in kind:
        k=kind[i]
        if k.startswith(('P','A','B2')):f=old[i];cnt['restore '+k.split('-tail')[0]]+=1
        else:f=logical(t);cnt['single '+k.split('-tail')[0]]+=1
    assert logical(f)==logical(t),i
    final[i]=f
print(cnt,'changed',sum(final[i]!=heads[i] for i in heads))
ids=list(final)
json.dump([final[i].replace('\\n','\n') for i in ids],open(S+'/f.in.json','w'),ensure_ascii=False)
subprocess.check_call(['node',S+'/measure.mjs',S+'/f.in.json',S+'/f.out.json'])
M=json.load(open(S+'/f.out.json'))
hz=lambda r:sum(1 for g in r['g'] if g[0] not in '，。、；：？！…—“”‘’（）《》【】　 ')
print('over',sum(max(r['occ'] for r in m)>462 for m in M),'rows',collections.Counter(len(m) for m in M),'tail<=1',collections.Counter(kind[ids[n]].split('-tail')[0] for n,m in enumerate(M) if len(m)==2 and hz(m[1])<=1))
json.dump(final,open(S+'/final.json','w'),ensure_ascii=False)
p=pathlib.Path('corpus/zh/battle/srvc-lines.json');raw=p.read_bytes();cur=hashlib.sha256(raw).hexdigest();doc=json.loads(raw)
for e in doc['entries']:e['translation']=final[e['id']]
out=(json.dumps(doc,ensure_ascii=False,indent=2)+'\n').encode();p.write_bytes(out);new=hashlib.sha256(out).hexdigest()
n=0
for c in pathlib.Path('config').rglob('*.json'):
    t=c.read_text(encoding='utf8')
    if cur in t:
        c.write_text(t.replace(cur,new).replace('"size": %d'%len(raw),'"size": %d'%len(out)),encoding='utf8');n+=1
print('locks',n,new[:12],len(out))
# mechanical refresh of literals pinned to the migrated layout, in the tests that pin battle lines
tests=['tests/test_community_feedback_battle_round_3.py','tests/test_community_feedback_battle_round_4.py','tests/test_community_feedback_final_pending.py','tests/test_community_feedback_stage_055.py','tests/test_community_feedback_stage_126.py','tests/test_release_workflow.py']
rep=0
for tp in tests:
    s=open(tp,encoding='utf8').read();o=s
    for i,t in heads.items():
        if final[i]==t:continue
        for a,b in ((t,final[i]),(t.replace('　','\\u3000'),final[i].replace('　','\\u3000')),(t.replace('\\n','\\\\n'),final[i].replace('\\n','\\\\n')),(t.replace('\\n','\\\\n').replace('　','\\u3000'),final[i].replace('\\n','\\\\n').replace('　','\\u3000'))):
            if a in s and "'"+i+"'" in s or a in s and '"'+i+'"' in s:
                c=s.count(a);s=s.replace(a,b);rep+=c
    if s!=o:open(tp,'w',encoding='utf8').write(s)
print('test literals',rep)
