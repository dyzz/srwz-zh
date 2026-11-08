"""Refresh candidate-only relocation tails from verified translated keyword fields."""
import sys,json
from pathlib import Path
sys.path.insert(0,'tools');import build_full_story_components as b
from srwz.runtime_keywords import load_keyword_authority,_discover_embedded_inventory,_aligned,_stage_relocation_plan
r=Path.cwd().resolve();assert 'candidates' in r.parts and (r/'config/text-layout/rendering-mode.json').is_file();cfg=json.loads((r/'config/full-story-components.json').read_text());ref=cfg['runtime_keywords'];fm=json.loads((r/'manifests/zh-release-font-validation.json').read_text())
_,patches,_=b._library_archive_offset_patches(ref['library_component_manifest']);elf,_=b._apply_library_archive_offset_patches((r/ref['original_executable']['path']).read_bytes(),patches)
source=b.load_text_table(r/'vendor/upstream-python/project/tbl_all.json');_,primary,aliases,_=b._full_story_overrides(fm);table=source
for over in (primary,aliases,b.original_fullwidth_ascii_overrides(source)):table=b.project_runtime_text_table(table,over)
a=load_keyword_authority((r/ref['catalog']['path']).read_bytes(),(r/ref['library_archive']['path']).read_bytes(),elf,table,table_start=int(ref['keyword_table_start'],0),table_end=int(ref['keyword_table_end'],0))
_,_,records,allocs=_discover_embedded_inventory((r/cfg['remaining_ui']['original_stage']['path']).read_bytes(),(r/cfg['full_story_stage']['hb']['path']).read_bytes(),a,source,runtime_base=int(ref['stage_runtime_base'],0),hb_table_start=ref['hb_table_start'],hb_table_end=ref['hb_table_end'],expected=ref['expected'])
by={(a.stage_index,a.offset):a for a in allocs}
for row in ref['stage_relocations']:
 donor=by[(row['stage_index'],int(row['donor_offset'],0))];src=by[(row['stage_index'],int(row['source_offset'],0))]
 print(row, 'new_offset',hex(donor.offset+_aligned(len(donor.target))),'donor',len(donor.target),donor.capacity,'source',len(src.target),src.capacity)
 row['relocation_offset']=hex(donor.offset+_aligned(len(donor.target)))
_stage_relocation_plan(ref['stage_relocations'],allocs,records,runtime_base=int(ref['stage_runtime_base'],0))
(r/'config/full-story-components.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
