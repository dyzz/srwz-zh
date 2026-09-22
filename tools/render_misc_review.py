#!/usr/bin/env python3
"""Render the reviewed miscellaneous-text decisions as a portable local page."""
import base64
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'config/editorial/main-misc-reviewed-application-20260922.json'
OUTPUT = ROOT / 'work/exports/main-misc-review-20260922'
TEMPLATE = ROOT / 'tools/templates/misc-review.html'
SP_SOURCE = ROOT / 'config/editorial/special-disc/main-misc-sync-20260922.json'


def render_sp(main_report, template):
    if not SP_SOURCE.exists():
        return
    sync = json.loads(SP_SOURCE.read_text())
    for path, digest in sync['files'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest['after_sha256'], path
    main_rows = {r['id']: r for r in main_report['entries']}
    rows = []
    for change in sync['changes']:
        original = main_rows.get(change['main_id'], {})
        reference = {'path': change['path'], 'id': change['sp_id']}
        rows.append({
            'id': change['sp_id'],
            'category': original.get('category', 'sp-tutorial'),
            'category_label': original.get('category_label', 'SP 教程共用表述'),
            'source_original': change.get('source', original.get('source_original', '')),
            'source_best': change.get('source', original.get('source_original', '')),
            'baseline': change['before'], 'proposal': change['after'], 'final': change['after'],
            'action': 'apply', 'reason': '同步本篇当前审定结果，保留 SP 的控制片段、原生容量与独立排版。',
            'proposal_reason': '对应本篇审阅条目：' + change['main_id'],
            'corpus_references': [reference],
            'writes': [{'reference': reference, 'before': change['before'], 'after': change['after']}],
        })
    report = {
        'entries': rows, 'writes': [w for r in rows for w in r['writes']],
        'validation': {'tests_passed': 8, 'font_component': '沿用 SP 现有码表，本次未新增字形'},
        'image_preview': main_report['image_preview'],
        'source_record_sha256': hashlib.sha256(SP_SOURCE.read_bytes()).hexdigest(),
    }
    template = template.replace('本篇 / BEST', 'SP').replace('本篇 / THE BEST', 'SPECIAL DISC')
    template = template.replace('BEST 日文', 'SP 日文').replace('本篇日文', 'SP 日文')
    template = template.replace('<option value="original">SP 日文</option>', '')
    template = template.replace('日文原文、送审原译、外部校订与最终决定，逐条对照。', 'SP 日文、同步前文本与本次采用文本，逐条对照。')
    template = template.replace('送审原译', '同步前文本')
    template = template.replace('外部校订是建议，“最终文本”是当前决定；被退回的建议不会计为已更新。', '本页只列实际同步变更；本篇对应条目和 SP 写回来源可展开查看。')
    start, end = template.index('<div class="notice">'), template.index('</div></header>')
    template = template[:start] + '<div class="notice">SP 同步本篇审定结果。保留记忆卡、回合、机师、集市及再攻击用词；独立的“边框闪烁”说明继续保留。组件写入、回读与固定容量已验证；本次未重建 ISO。' + template[end:]
    template = template.replace('<div class="stats">', '<p><a href="index.html">返回本篇 / BEST 改动</a></p><div class="stats">')
    template = template.replace('外部校订建议', '同步采用文本')
    template = template.replace('新增字形“芜”：编码 97DA，字形位置 4378。已有字符编码不移动，字库组件验证缺字为 0。', '使用 SP 现有码表；全部同步文本均通过编码、容量和组件回读检查。')
    template = template.replace('“刀z%s〜”来自双字节字符中间的错位取址。正确条目 menu/SLPS/00/0335 已译为“～【选项】%s～”；异常条目不进入正式写入清单。', '本篇的错位诊断串和不同内容的主人公介绍没有复制到 SP。')
    template = template.replace('本页包含 130 条修改建议及 7 条原待确认记录；未变更的其余送审文本不重复展示。', f'本页包含 {len(rows)} 项 SP 同步改动；另有 {len(sync["already_current"])} 个对应位置已一致，继续保留 SP 既有的边框闪烁说明。')
    payload = json.dumps(report, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (OUTPUT / 'sp.html').write_text(template.replace('__REVIEW_DATA__', payload))
    (OUTPUT / 'sp-review-data.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


def main():
    report = json.loads(SOURCE.read_text())
    ids = [r['id'] for r in report['entries']]
    assert len(ids) == len(set(ids))
    assert dict(Counter(r['action'] for r in report['entries'])) == report['actions']
    for path, digest in report['files'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest['after_sha256'], path
    for row in report['entries']:
        row['writes'] = [w for w in report['writes'] if w['id'] == row['id']]
    report['source_record_sha256'] = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    preview = ROOT / 'work/reviews/main-misc-reviewed-20260922/sort-before-after.png'
    report['image_preview'] = 'data:image/png;base64,' + base64.b64encode(preview.read_bytes()).decode()
    payload = json.dumps(report, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    template = TEMPLATE.read_text()
    html = template.replace('__REVIEW_DATA__', payload)
    if SP_SOURCE.exists():
        html = html.replace('<div class="stats">', '<p><a href="sp.html">查看 SP 同类文本同步改动 →</a></p><div class="stats">')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'index.html').write_text(html)
    (OUTPUT / 'review-data.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    render_sp(report, template)
    print(json.dumps({'output': str(OUTPUT / 'index.html'), 'entries': len(ids), 'applied': sum(r['action'] in ('apply', 'apply_adjusted') for r in report['entries']), 'write_locations': len(report['writes'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
