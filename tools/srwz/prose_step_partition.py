"""Fixed-step minimax range partition, exact row count and native hard blanks."""
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
from math import ceil,floor
from srwz.chinese_layout import tokenize_dialogue,_valid_break,_occupied_width_index

def balance(blocks,counts,scene,profile,engine,terms,group,meta,encode,row_count=None,common_width=False,anchor_slack=0,fill_rows=False):
 tokens=[];ends=[];blanks={};pending=[]
 for block in blocks:
  if isinstance(block,str):
   blanks.setdefault(len(tokens),[]).append(block);continue
  ts=tokenize_dialogue(engine.measure(block[0],scene),protected_terms=(),default_advance_px=scene.step_x,protect_words=False)
  indent=block[1] if len(block)>1 else ""
  if indent:
   ts=(replace(ts[0],text=indent+ts[0].text,width=ts[0].width+len(indent)),*ts[1:])
  tokens.extend(ts);ends.append(len(tokens))
 n=len(tokens);rows=row_count or sum(counts);sx=scene.step_x;cap=profile.maximum_width*sx
 prefix=[0]
 for t in tokens:prefix.append(prefix[-1]+int(t.width*sx))
 block_starts=[0]+ends[:-1]
 block_required={end:max(0,cap-anchor_slack) if prefix[end]-prefix[start]>=cap else 0 for start,end in zip(block_starts,ends)}
 total=prefix[-1];width=_occupied_width_index(tokens)
 edges=[[] for _ in range(n)]
 for a in range(n):
  stop=next(e for e in ends if e>a)
  for b in range(a+1,stop+1):
   occupied=width(a,b)*sx
   if occupied>cap:break
   if b!=stop and not _valid_break(tokens,b):continue
   value=prefix[b]-prefix[a]
   text=''.join(t.text for t in tokens[a:b]);raw=engine.strip(text)
   size=encode(raw) if len(group)>1 else 0
   edges[a].append((b,value,raw,size))
 def search(lo,hi,reconstruct=False):
  @lru_cache(None)
  def solve(a,k,anchored=False):
   if k==rows:return () if a==n else None
   if a==n:return None
   left=rows-k;remaining=total-prefix[a]
   if remaining<left*lo or remaining>left*hi:return None
   best=None
   for b,v,raw,size in edges[a]:
    if v<lo:continue
    if v>hi:break
    if len(group)>1:
     m=meta[group[k]['id']]
     if size+(m['terminator']=='nul')>m['capacity']:continue
    end=next(e for e in ends if e>a)
    has_anchor=anchored or v>=block_required[end]
    if common_width and b==end and not has_anchor:continue
    tail=solve(b,k+1,has_anchor if b!=end else False)
    if tail is None:continue
    if not reconstruct:return ((b,raw,v),)+tail
    cost=(v*rows-total)**2+sum((x[2]*rows-total)**2 for x in tail)
    result=((b,raw,v),)+tail
    score=(cost,tuple(-x[2] for x in result))
    if best is None or score<best[0]:best=(score,result)
   return best[1] if best else None
  return solve(0,0)
 def feasible(spread):
  for lo in range(max(1,ceil(total/rows-spread)),min(floor(total/rows),cap-spread)+1):
   result=search(lo,lo+spread)
   if result is not None:return lo,result
  return None
 if fill_rows:
  @lru_cache(None)
  def fullest(a,k):
   if k==rows:return () if a==n else None
   if a==n:return None
   for b,v,raw,size in reversed(edges[a]):
    if len(group)>1:
     m=meta[group[k]['id']]
     if size+(m['terminator']=='nul')>m['capacity']:continue
    tail=fullest(b,k+1)
    if tail is not None:return ((b,raw,v),)+tail
   return None
  selected=fullest(0,0);assert selected is not None
  best=(0,selected);values=[x[2] for x in selected];low=max(values)-min(values)
 else:
  low,high=0,cap-1
  assert feasible(high) is not None
  while low<high:
   mid=(low+high)//2
   if feasible(mid) is None:low=mid+1
   else:high=mid
  best=None
  for lo in range(max(1,ceil(total/rows-low)),min(floor(total/rows),cap-low)+1):
   result=search(lo,lo+low,True)
   if result is None:continue
   score=(sum((x[2]*rows-total)**2 for x in result),tuple(-x[2] for x in result))
   if best is None or score<best[0]:best=(score,result)
 result=[];last=0
 for end,raw,value in best[1]:
  if last in blanks:result.extend(blanks[last])
  result.append(raw);last=end
 result.extend(blanks.get(n,[]))
 return result,dict(range_px=low,rows=rows,average_step_sum=total/rows,optimal_range_verified=not fill_rows,front_to_back_maximum_fill_verified=fill_rows,common_width_required=common_width,common_width_px=cap,anchor_slack=anchor_slack)
