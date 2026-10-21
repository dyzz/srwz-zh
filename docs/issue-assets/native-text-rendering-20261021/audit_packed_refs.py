"""Incoming direct-reference audit for analysis-only packed control handlers.
Raw pointer candidates are reported, not silently treated as reachable calls.
No conclusion about pointers manufactured dynamically by unexamined code.
"""
from pathlib import Path
import sys,json,struct
OUT=Path(__file__).parent;sys.path.insert(0,str(OUT.parents[2]/'tools'))
from inventory import native
from resource_inventory import text_sections
from optical_packed_candidate import candidate
results=[]
for ed in ('original','best','sp'):
 e,lock=native(ed);proof=candidate(e,ed);base=proof['writes'][0][0];geometry=int(proof['geometry_va'],16);old_entries=[base+32*i for i in range(5)];table=proof['writes'][2][0];direct=[];literal=[]
 for va,off,size in text_sections(e):
  for pc in range(va,va+size,4):
   w=e.words(pc,1)[0];op=w>>26;dest=None
   if op in (1,4,5,6,7,20,21,22,23):dest=pc+4+4*((w&65535)-65536 if w&32768 else w&65535)
   elif op in (2,3):dest=(w&0x3ffffff)<<2
   if dest is not None and (base<=dest<base+144 or geometry<dest<geometry+40 or dest==geometry+0x54):direct.append(dict(site=hex(pc),target=hex(dest),word=hex(w)))
   if w in old_entries:literal.append(dict(site=hex(pc),target=hex(w),expected_control_table_entry=table<=pc<table+20))
 assert not direct,(ed,'unexpected incoming direct transfer',direct)
 assert len(literal)==5 and all(r['expected_control_table_entry'] for r in literal),(ed,'unexpected raw pointer candidates',literal)
 mode_writes=[];delta=base-0x13a470
 for pc in range(0x13a290+delta,0x13ac88+delta,4):
  w=e.words(pc,1)[0]
  if w>>26 in (0x28,0x29,0x2b) and w>>21&31==17 and w&65535==0x48:
   mode_writes.append(dict(site=hex(pc),source_register=w>>16&31))
 assert [r['source_register'] for r in mode_writes]==[0,0,0,0,3],(ed,'mode provenance changed',mode_writes)
 assert mode_writes[-1]['site']==hex(0x13ac64+delta)
 results.append(dict(edition=ed,classification_mode_writes=mode_writes,inline_Y_invariant='entry flag0; optical height sets flag1 and mode0; all in-parse mode writes are zero; saved mode restore is after glyph construction',native_executable=lock,control_span=[hex(base),hex(base+144)],incoming_direct_transfer_candidates=direct,raw_old_handler_pointer_candidates=literal,patch=dict(control_entries=proof['control_entries'],palette_tail=proof['palette_tail'],all_writes_file_backed=proof['all_writes_file_backed'],source_span_sha256=proof['original_control_span_sha256'],replacement_span_sha256=proof['packed_span_sha256'],writes=[dict(address=hex(a),size=len(b)) for a,b in proof['writes']])))
 print(ed,'packed controls: no incoming direct transfers; five old-handler literals belong only to control jump table',flush=True)
(OUT/'optical-packed-reference-audit.json').write_text(json.dumps(dict(scope=__doc__,status='three_native_packed_patch_preimages_and_scanned_incoming_references_checked',editions=results),indent=2)+'\n')
