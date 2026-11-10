import json,re,subprocess,collections,os,random
S=os.path.dirname(os.path.abspath(__file__))
old={e['id']:e['translation'] for e in json.loads(subprocess.check_output(['git','show','756a5ac0^:corpus/zh/battle/srvc-lines.json']))['entries']}
new={e['id']:e['translation'] for e in json.load(open('corpus/zh/battle/srvc-lines.json'))['entries']}
p=json.load(open('work/review/battle-polish-20261109/protected.json'))
prot=set(p if isinstance(p,list) else (p.get('ids') or p.keys()))
print('prot',len(prot),list(prot)[:3])
ids=list(new);M=json.load(open(S+'/st.out.json'))
NAT='，。、；：？！…—'
hzcount=lambda r:sum(1 for g in r['g'] if g[0] not in '，。、；：？！…—“”‘’（）《》【】　 ')
C=collections.defaultdict(list)
for n,i in enumerate(ids):
    o,w,l=M[3*n],M[3*n+1],M[3*n+2]
    if len(o)!=2:continue
    lastc=o[0]['g'][-1][0]; tailhz=hzcount(o[1]); fit=l[0]['occ']<=462
    if i in prot: k='P'
    elif tailhz==0: k='C-quote-alone'
    elif lastc in NAT: k='A-natural'
    elif fit: k='B1-mid-fits'
    else: k='B2-mid-long'
    k2=k+('-tail1' if tailhz==1 else '')
    C[k2].append(i)
for k in sorted(C):print(k,len(C[k]))
random.seed(1)
for k in sorted(C):
    if k.startswith('A-natural') and not k.endswith('tail1'):continue
    print('==',k)
    for i in random.sample(C[k],min(9,len(C[k]))):print(i,old[i].replace('\\n','⏎').replace('　',''),' || ',new[i].replace('\\n','⏎').replace('　',''))
json.dump(C,open(S+'/classes.json','w'))
