#!/usr/bin/env python3
"""Audit corpus control preservation and cell/pixel/authoring agreement."""
from pathlib import Path
import argparse,collections,hashlib,json,math,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from srwz.text import (control_notation_tokens,encode_text,load_text_table,
                      runtime_control_bytes,verify_runtime_control_bytes,
                      unrecognized_control_notation_offsets, RUNTIME_SQUARE_PARAMETER_TOKEN)
from srwz.chinese_layout import tokenize_dialogue,dialogue_line_widths
from srwz.renderer_metrics import text_extent
from srwz.library_typography import library_typography
from srwz.compact_authoring import compact_controlled_text
from srwz.control_layout import require_static_layout


def audit(root=ROOT):
    table=load_text_table(root/'vendor/upstream-python/project/tbl_all.json')
    # Deliberately override every visible protocol punctuation/digit. Complete
    # controls must bypass these glyph mappings, including the native @ prefix.
    overrides={ch:0x9800+i for i,ch in enumerate('@-+%{}<>[]. 0123456789')}
    selection=json.loads((root/'config/fonts/zh-release-font.json').read_text())['translation_tree_selection']
    map_fields=set(selection['map_fields'])
    forms={};failures=[];deferred=[];unknown=[];files=fields=0;inputs=[]
    def walk(node,pointer=''):
        if isinstance(node,dict):
            for k,v in node.items():
                ptr=pointer+'/'+str(k)
                if k in ('translation','source_text') and isinstance(v,str):yield ptr,v
                elif k in map_fields and isinstance(v,dict):
                    for identity,translated in v.items():
                        if isinstance(translated,str):yield ptr+'/'+str(identity),translated
                else:yield from walk(v,ptr)
        elif isinstance(node,list):
            for i,v in enumerate(node):yield from walk(v,pointer+'/'+str(i))
    for p in sorted((root/'corpus/zh').rglob('*.json')):
        n=0
        for pointer,text in walk(json.loads(p.read_text())):
            fields+=1;n+=1;owner=dict(path=str(p.relative_to(root)),pointer=pointer)
            try:tokens=control_notation_tokens(text)
            except ValueError as exc:
                failures.append(dict(**owner,check='tokenize',error=str(exc)));continue
            for t in tokens:forms.setdefault(t.text,dict(kind=t.kind,owner=owner))
            if '＜ｔｍ＞' in text or '<tm>' in text or text.startswith('@') or RUNTIME_SQUARE_PARAMETER_TOKEN.search(text):
                deferred.append(dict(**owner,text=text,reason='owner-specific dynamic/repeat stream; generic reflow excluded'))
            offsets=unrecognized_control_notation_offsets(text)
            if offsets:unknown.append(dict(**owner,offsets=list(offsets),text=text))
        if n:
            files+=1;inputs.append(dict(path=str(p.relative_to(root)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    checks=collections.Counter();records=[]
    for form,meta in sorted(forms.items()):
        row=dict(form=form,**meta)
        try:
            controls=runtime_control_bytes(form)
            if controls:
                encoded=encode_text(form,table,overrides=overrides)
                assert verify_runtime_control_bytes(encoded,table,form)==controls
                assert encoded==b''.join(controls)
                checks['native_control_byte_forms']+=1
                row['native_hex']=encoded.hex()
            compiled=library_typography(form,'DSCR',domain='character')
            assert runtime_control_bytes(compiled)==controls
            assert compact_controlled_text(form,default_width=21)==form
            checks['authoring_preserves_control_forms']+=1
            if form.startswith(('@','[')):
                for fn in (lambda:require_static_layout(form),lambda:text_extent(form,default_advance_px=21),lambda:tokenize_dialogue(form,default_advance_px=21)):
                    try:fn()
                    except ValueError:pass
                    else:raise AssertionError('repeat stream silently accepted as static text')
                checks['owner_specific_forms_explicitly_routed']+=1
            else:
                text='甲'+form+'乙';controlled='<width:15><space:15>'+text
                a=text_extent(text,default_advance_px=21);b=text_extent(controlled,default_advance_px=21)
                # Dimension forms intentionally change the baseline; compare
                # plain/pixel paths under exactly the same inline metrics.
                for probe in (text,controlled):
                    extent=text_extent(probe,default_advance_px=21)
                    assert dialogue_line_widths(probe,default_advance_px=21)==(math.ceil(extent.occupied_px/21),)
                    assert any(form in t.text for t in tokenize_dialogue(probe,default_advance_px=21))
                assert (a.advance_px,a.occupied_px)==(b.advance_px,b.occupied_px)
                checks['cell_pixel_atomic_forms']+=1
            row['passed']=True
        except (ValueError,AssertionError) as exc:
            row['passed']=False;row['error']=str(exc);failures.append(dict(check='form_contract',**row))
        records.append(row)
    return dict(passed=not failures and not unknown,scope='all corpus/zh translation/source_text fields including duplicates and inactive sources; tool contracts, not whole-game runtime proof',scanned_files=files,scanned_fields=fields,unique_forms=len(forms),checks=dict(checks),failures=failures,unrecognized_syntax=unknown,owner_specific_streams=deferred,forms=records,inputs=inputs)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    d=audit();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:d[k] for k in ('passed','scanned_files','scanned_fields','unique_forms','checks')},ensure_ascii=False));print('failures',len(d['failures']),'unknown syntax',len(d['unrecognized_syntax']),'owner-specific streams',len(d['owner_specific_streams']))
    return 0 if d['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
