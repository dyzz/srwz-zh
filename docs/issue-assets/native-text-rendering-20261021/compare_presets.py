"""Compare sampled native preset row values; LCS is not caller equivalence proof."""
from pathlib import Path
import json
OUT=Path(__file__).parent;j=json.loads((OUT/'preset-inventory.json').read_text());a,b,c=[x['sampled_rows'] for x in j['editions']];assert a==b
n,m=len(a),len(c);d=[[0]*(m+1) for _ in range(n+1)]
for i in range(n-1,-1,-1):
 for k in range(m-1,-1,-1):d[i][k]=1+d[i+1][k+1] if a[i]==c[k] else max(d[i+1][k],d[i][k+1])
i=k=0;matches=[];extra=[];unmatched=[]
while i<n and k<m:
 if a[i]==c[k]:matches.append([i,k]);i+=1;k+=1
 elif d[i+1][k]>d[i][k+1]:unmatched.append(i);i+=1
 else:extra.append(k);k+=1
unmatched+=list(range(i,n));extra+=list(range(k,m))
r={'scope':'Value sequence comparison of sampled rows; duplicate rows make semantic identity ambiguous. LCS chosen alignment is a candidate mapping, not call-site equivalence proof.','original_best_equal':True,'sampled_rows':{'original':n,'best':len(b),'sp':m},'equal_row_pairs':matches,'unmatched_original_rows':unmatched,'extra_sp_rows':[{'row':x,'values':c[x]} for x in extra]}
(OUT/'preset-semantic-comparison.json').write_text(json.dumps(r,indent=2)+'\n');print('Original/Best rows equal;',len(matches),'matching Original/SP rows;',len(extra),'SP-only rows in sampled sequence')
