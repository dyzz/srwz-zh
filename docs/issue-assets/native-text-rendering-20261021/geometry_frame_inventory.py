"""Native parser frame ownership and direct cached-height reset evidence.
Only the parser and its two original direct callees are covered; no claim
about arbitrary indirect execution or asynchronous re-entry into the renderer.
"""
from pathlib import Path
import json,struct,hashlib
from inventory import native
from execute import run_case
OUT=Path(__file__).parent;inventory=json.loads((OUT/'inventory.json').read_text());frames=[];resets=[]
widths={0x20:1,0x24:1,0x28:1,0x21:2,0x25:2,0x29:2,0x23:4,0x27:4,0x2b:4,0x37:8,0x3f:8,0x1e:16,0x1f:16}
for ed in ('original','best','sp'):
 e,lock=native(ed);r=next(x for x in inventory['editions'] if x['edition']==ed);delta=int(r['core_va_delta'],16);parser=0x13a290+delta;packet=0x13aca0+delta;reset=int(r['initializer_entry'],16);functions=[]
 for name,start,end,frame_size in [('parser',parser,0x13ac88+delta,96),('packet_builder',packet,0x13bd60+delta,48),('reset',reset,reset+0x11c,0)]:
  accesses=[];sp_arithmetic=[];calls=[]
  for pc in range(start,end,4):
   w=e.words(pc,1)[0];op=w>>26;rs=w>>21&31;rt=w>>16&31;rd=w>>11&31;fn=w&63;im=w&65535;im=im-65536 if im&32768 else im
   if op in widths and rs==29:
    access=dict(pc=hex(pc),opcode=hex(w),offset=im,size=widths[op],store=op in (0x28,0x29,0x2b,0x3f,0x1f));accesses.append(access)
    assert 0<=im and im+widths[op]<=frame_size,(ed,name,'out-of-frame access',access)
    if name=='parser':assert im+widths[op]<=0x58,(ed,name,'candidate flag overlaps native use')
   elif op in (8,9,0x19) and (rs==29 or rt==29):
    assert rs==29 and rt==29 and abs(im)==frame_size,(ed,name,'unexpected SP alias')
    sp_arithmetic.append(dict(pc=hex(pc),delta=im))
   elif op==0 and (rs==29 or rt==29 or rd==29):raise AssertionError((ed,name,'unexpected SP register use',hex(pc),hex(w)))
   if op==3:calls.append(dict(site=hex(pc),target=hex((w&0x3ffffff)<<2)))
   if op==0 and fn==9:raise AssertionError((ed,name,'indirect call',hex(pc)))
  if name=='parser':assert [x['target'] for x in calls]==[hex(reset),hex(packet)]
  else:assert not calls,(ed,name,'unexpected callee')
  functions.append(dict(name=name,start=hex(start),end=hex(end),frame_size=frame_size,stack_accesses=accesses,stack_adjustments=sp_arithmetic,direct_calls=calls,sha256=hashlib.sha256(e.read(start,end-start)).hexdigest()))
 assert e.words(0x13a38c+delta,1)==(0,)
 frames.append(dict(edition=ed,native_executable=lock,functions=functions,candidate_call_local_flag=dict(offset=0x58,size=4,overlap_with_native_parser_frame=False,entry_zero_site=hex(0x13a38c+delta))))
 for height in (11,12,13,14):
  payload=bytes([0x33,height])+bytes.fromhex('826030ff889f');actual=run_case(ed,payload,details=True)
  geometries=[g['render'] for g in actual['glyphs']];assert geometries==[[21,height],[21,height]],(ed,height,geometries);assert actual['explicit'][:2]==[22,11]
  resets.append(dict(edition=ed,stream_hex=payload.hex(' '),height_before_reset=height,rendered_geometry=geometries,returned_explicit_metrics=actual['explicit'],returned_pen=actual['cursor'],glyph_trace=actual['glyphs'],state_sha256=hashlib.sha256(bytes.fromhex(actual['final_state'])).hexdigest()))
 print(ed,'parser frame+58 unused by native parser/callees; four original cached-height reset cases verified',flush=True)
(OUT/'geometry-frame-inventory.json').write_text(json.dumps(dict(scope=__doc__,status='three_native_frame_ownership_and_callee_stack_bounds_checked',editions=frames),indent=2)+'\n')
(OUT/'reset-cached-height-execution.json').write_text(json.dumps(dict(scope=__doc__,status='native_reset_changes_persistent_metrics_but_keeps_current_parse_working_geometry',case_count=len(resets),cases=resets),indent=2)+'\n')
