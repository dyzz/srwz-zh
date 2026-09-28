#!/usr/bin/env python3
"""Build a local-only decision page from the confirmed source inventory."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.text import CONTROL_NOTATION


def display_text(text: str) -> str:
    def visible_token(match):
        token = match.group()
        if token.startswith('$'):
            return f'【变量 {token}】'
        if token.startswith('%'):
            return f'【动态值 {token}】'
        return ''
    return CONTROL_NOTATION.sub(visible_token, text)


def resolve(document, pointer):
    for part in pointer.lstrip('/').split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        document = document[int(key)] if isinstance(document, list) else document[key]
    return document


def build(scope_path: Path, preview_path: Path, output: Path, width_report: Path | None = None, applied_receipt: Path | None = None, execution_receipts: list[Path] | None = None, current_quality: Path | None = None, runtime_report: Path | None = None):
    scope = json.loads(scope_path.read_text())
    applied=json.loads(applied_receipt.read_text()) if applied_receipt else None
    executions=[json.loads(p.read_text()) for p in execution_receipts or []]
    receipts=([applied] if applied else [])+executions
    source_paths={}
    for relative, expected in scope['corpus_input_sha256'].items():
        source=ROOT/relative
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            refs=[r['sources'][relative] for r in receipts if relative in r.get('sources',{})]
            current=expected
            for ref in refs:
                if ref['before_sha256']!=current:
                    raise ValueError(f'Execution source chain drift: {relative}')
                current=ref['after_sha256']
            if not refs or hashlib.sha256(source.read_bytes()).hexdigest()!=current:
                raise ValueError(f'Source changed outside execution receipts: {relative}')
            source=ROOT/refs[0]['snapshot']
            if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
                raise ValueError(f'Applied snapshot drift: {relative}')
        source_paths[relative]=source
    preview = json.loads(preview_path.read_text())
    documents = {}
    current_documents = {}
    rows = []
    applied_keys={(x['path'],x['id']) for x in applied.get('changes',[])} if applied else set()
    execution_keys={(x['path'],x['id']) for r in executions for x in r.get('changes',[])}
    applied_keys |= execution_keys
    outcomes={(x['path'],x['id']):x.get('outcome','written') for r in executions for x in r.get('changes',[])}
    decisions=json.loads((ROOT/'config/text-layout/compact-special-decisions-20260928.json').read_text())
    user_choices={(x['path'],x['json_pointer']):x['decision'] for x in decisions['records']}
    reasons = {
        'plain_candidate': '英数表达式达到 3 字符门槛，按统一规则收窄；中文及正文标点恢复原宽。',
        'symbol_review': '表达式邻接特殊符号：先确认字形与表达式边界，再应用收窄规则。',
        'existing_dimensions_review': '含既有特殊控制语法（包括 <<width:XX>> 按钮／图标相关标记）：保留原生标记，单独处理 TRI、EXP 或数值表达式；不能当成已经加入的窄距标签。',
        'other_controls_review': '原有控制码和变量完整保留，不重写、不对语法本身加窄距标签；固定文字另按显示面验证。',
        'dynamic_template': '动态模板：保留模板语法，检查展开后的最大宽度。',
        'texture_glyph_review': '图片文字：在图片排版中调整字形与宽度，不能加入文本标签。',
    }
    pending_notes = {
        'library_metadata':'图鉴字段使用原生自动英数字距；标签会生效，但恢复值需按字段验证。',
        'name_authoring_sources':'共享名称池、固定槽位和多个显示栏位需一起处理；长武器名实测仍会覆盖类别栏。',
        'sp_names':'SP 名称迁移和共享显示消费者需验证恢复字距与槽位。',
        'speaker_and_pilot_names':'姓名字段共享于多个显示面，需核对消费者与槽位容量。',
        'main_fixed_help_qa':'Q&A/教程先按逻辑文字和颜色记录定位，再处理窄距；标签不能按普通字符参与计数。',
        'main_menu_and_help':'菜单/帮助的固定槽位、可执行程序字段和图标变量路径需分别预检。',
        'sp_native_ui':'SP 原生界面的固定槽位和默认字距需按实际消费者核对。',
        'main_flow_short':'短摘要固定三行，需同时满足编码字节和像素预算。',
        'sp_flow_short':'SP 短摘要固定三行，需同时满足编码字节和像素预算。',
        'sp_fixed_pages':'固定行格的标签占用物理字节，需同时检查行格与像素预算。',
        'main_conditions':'条件中的原生姓名/数值变量保留，需检查最宽展开值。',
        'sp_conditions':'SP 条件中的原生模板和变量保留，需检查最宽展开值。',
        'work_titles':'作品标题需确认固定字段及绘制路径的控制码支持。',
        'stage_and_chapter_titles':'关卡/章节标题需按固定字段及绘制路径处理。',
        'sp_stage_titles':'SP 标题需按版本固定字段及绘制路径处理。',
        'main_z_reports':'Z 报告需核对消费者控制码支持和固定字段分配。',
        'main_flow_long':'该长梗概原分行无需改变，尚需追加英数表达式窄距及固定容量验证。',
    }
    for record in scope['records']:
        path = record['path']
        if path not in documents:
            documents[path] = json.loads(source_paths[path].read_text())
            current_documents[path] = json.loads((ROOT/path).read_text())
        raw = resolve(documents[path], record['json_pointer'])
        text = raw.replace('\\n', '\n')
        mode = ('batch' if record.get('status') == 'plain_candidate' else
                'special' if 'compact' in record['queues'] else 'keep')
        reason = reasons.get(record.get('status'),
            '没有达到 3 字符门槛的固定英数表达式，本轮不加入收窄标签。已有符号、变量和正文保持逻辑内容。')
        key=(path,record['id'])
        outcome=outcomes.get(key,'prose_written' if key in applied_keys else 'pending_technical' if 'compact' in record['queues'] else 'outside_compact_batch')
        if user_choices.get((path,record['json_pointer']))=='keep':outcome='user_keep'
        current_raw=resolve(current_documents[path],record['json_pointer']).replace('\\n','\n')
        if outcome=='pending_technical':
            reason=pending_notes.get(record['group'],reason)
        if outcome=='catalog_link_preserved':
            reason='混合语言词条名保持原生链接文本，周围对白按原宽重新检查；词条内部不加入窄距标签。'
        if outcome=='retained_due_fixed_allocation':
            reason='已检查编码容量：闭合收窄标签超出原固定字段；保留完整译文及双字节英数，后续需要消费者层面的排版处理。'
        rows.append(dict(record, text=display_text(text), raw=text,applied=key in applied_keys,outcome=outcome,
            current_text=display_text(current_raw),current_raw=current_raw,
            mode=mode, reason=reason, editions=record.get('editions',
                ['original', 'best', 'sp'] if record['group'].startswith('library_') else
                ['sp'] if '/special-disc/' in path else ['original', 'best'])))

    originals = {(record['path'], record['id']): record['before']
                 for record in preview['records'] if 'before' in record}
    selected = {}
    for record in preview['records']:
        key = record['path'], record['id']
        if key not in selected or record['variant'] == 'balanced_compact':
            selected[key] = record
    prose = []
    for record in selected.values():
        error = record.get('error')
        before = display_text(record.get('before', originals.get((record['path'], record['id']), '')))
        after = display_text(record.get('after', ''))
        focus = record['id'] in ('library-text/2755c95ab9cf91f5',
            'library-text/c5c3bc8563abe5e6','summary/00/000','summary/01/000')
        prose.append(dict(record, before=before, after=after, error=error, focus=focus,
            decision='blocked' if error else 'change' if before != after else 'same',
            editions=['sp'] if record['surface'].startswith('sp_') else
                ['original', 'best', 'sp'] if record['surface'].startswith('library_') else ['original', 'best']))
    counts = dict(Counter(row['mode'] for row in rows))
    prose_counts = dict(Counter(row['decision'] for row in prose))
    assert sum(counts.values()) == scope['review_union_owners']
    assert counts['batch'] + counts['special'] == scope['candidate_owners']
    prose_counts.setdefault('blocked',0)
    assert sum(row['focus'] for row in prose) == 4
    special_counts = dict(Counter(row['status'] for row in rows if row['mode'] == 'special'))
    assert sum(special_counts.values()) == counts['special']
    data = dict(source=scope['source_commit'], counts=counts, specialCounts=special_counts, proseCounts=prose_counts,
        runs=scope['eligible_runs'], numericRuns=scope['numeric_expression_runs'], rows=rows, prose=prose,
        widthReport=json.loads(width_report.read_text()) if width_report else None,applied=applied,
        executionCounts=dict(Counter(r['outcome'] for r in rows if 'compact' in r['queues'])))
    if applied and applied.get('quality'):
        quality=ROOT/applied['quality']['path']
        if hashlib.sha256(quality.read_bytes()).hexdigest()!=applied['quality']['sha256']:
            raise ValueError('Optimization quality proof drift')
        data['quality']=json.loads(quality.read_text())
    if current_quality:
        data['quality']=json.loads(current_quality.read_text())
        data['quality_source']='current_local_corpus'
    if runtime_report:
        runtime=json.loads(runtime_report.read_text())
        for edition,row in runtime['editions'].items():
            build_path=ROOT/row['build_receipt']
            current=json.loads(build_path.read_text())
            if current['output']!=row['iso']:
                raise ValueError(f'Runtime ISO binding drift: {edition}')
            if hashlib.sha256(build_path.read_bytes()).hexdigest()!=row['build_receipt_sha256']:
                raise ValueError(f'Runtime build receipt drift: {edition}')
            readback=ROOT/row['readback']['path']
            if hashlib.sha256(readback.read_bytes()).hexdigest()!=row['readback']['sha256']:
                raise ValueError(f'Runtime readback receipt drift: {edition}')
            for case in row['cases']:
                path=ROOT/case['path']
                if hashlib.sha256(path.read_bytes()).hexdigest()!=case['sha256']:
                    raise ValueError(f'Runtime screenshot drift: {path}')
        data['runtime']=runtime
    embedded = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    template = (ROOT / 'tools/text_layout/local-decisions.html').read_text()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace('__DECISION_DATA__', embedded))
    return dict(counts=counts, prose=prose_counts, output=str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', type=Path, required=True)
    parser.add_argument('--preview', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--width-report', type=Path)
    parser.add_argument('--current-quality', type=Path)
    parser.add_argument('--runtime-report', type=Path)
    parser.add_argument('--applied-receipt', type=Path)
    parser.add_argument('--execution-receipt', type=Path, action='append',default=[])
    args = parser.parse_args()
    print(json.dumps(build(args.scope, args.preview, args.output,args.width_report,args.applied_receipt,args.execution_receipt, args.current_quality,args.runtime_report), ensure_ascii=False))


if __name__ == '__main__':
    main()
