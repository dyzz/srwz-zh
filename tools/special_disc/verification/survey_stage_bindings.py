"""Read-only native binding inventory for all SP STAGE chunks.

This is an editorial/binding survey, not a writer or runtime acceptance report.
"""
from pathlib import Path
import collections
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/special_disc/writeback")]
import migrate_stage_dialogue as st
from stage_bindings import StageBindings, BindingError
from srwz.codec import decode_production
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.text import load_text_table


def main():
    root = ROOT
    sd = st.sd
    T = load_text_table(st.mst.TABLE)
    mod = sd.sd_stage_module()
    hb = st.read_disc_member(st.HB)
    exe = st.read_disc_member("SLPS_259.20")
    functions = mod.read_stage_function_addresses(exe, start=sd.SD_FUNCTION_TABLE[0], end=sd.SD_FUNCTION_TABLE[1])
    data = (st.BASE / st.STAGE).read_bytes()
    base_report = json.loads((st.BASE / "report.json").read_text())
    if st.sha256(data) != base_report["files"][st.STAGE]:
        raise ValueError("base STAGE drift")
    off = read_executable_archive_offsets(hb, ExecutableOffsetSpec(
        name="SP STAGE", member=st.HB, table_start=sd.HB_STAGE_TABLE,
        table_end=sd.HB_STAGE_TABLE + st.HB_TABLE_SPAN), len(data))
    b=StageBindings(root,allow_draft=True);result=[];errors=[];counts=collections.Counter();matched=set()
    for i in range(1,len(off)-1):
     try:
      d=decode_production(data[off[i]:off[i+1]]).output
      p=mod.parse_stage(d,T,stage_index=i,function_address=functions[i],base_address=sd.SD_STAGE_BASE)
     except ValueError as error:
      errors.append(dict(chunk=i,reason=str(error)));continue
     if not p.entries:continue
     rows=[]
     for e in p.entries:
      target=st.native_id(i,e.entry_id)
      try:
       r=b.resolve(target,e.kind,e.text);status='bound';matched.add(target);counts[r['route']]+=1
       rows.append(dict(target=target,kind=e.kind,source_text_sha256=r['source_text_sha256'],route=r['route'],pointer_offset=e.pointer_offset,text_offset=e.text_offset))
      except BindingError as error:
       status='unresolved';rows.append(dict(target=target,kind=e.kind,source=e.text,reason=str(error),pointer_offset=e.pointer_offset,text_offset=e.text_offset))
      counts[status]+=1
     result.append(dict(chunk=i,name=d[0x30:0x50].split(b'\0',1)[0].decode('ascii'),records=len(rows),unresolved=sum('reason' in r for r in rows),entries=rows))
    out=root/'work/review/special-disc/status/native-binding-inventory.json'
    report=dict(schema_version=1,scope='read-only STAGE survey, not a writeback coverage claim',base_stage_sha256=st.sha256(data),inputs=b.inputs,counts=dict(counts),parsed_chunks=len(result),parse_failures=errors,chunks=result,pending_native_targets=sorted(t for t in b.direct if t.startswith(('sd/story/','sd/challenge/')) and t not in matched))
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(counts=counts,parsed_chunks=len(result),parse_failures=errors),ensure_ascii=False))


if __name__ == "__main__":
    main()
