#!/usr/bin/env python3
"""Build and serve the 55-item local typography decision queue (no corpus writeback)."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'work/reviews/compact-inventory-20260928'
DEFAULT = BASE / 'special-confirmation'
CATEGORIES = {'symbol_review': '符号边界', 'existing_dimensions_review': '既有特殊控制语法',
              'dynamic_template': '动态模板', 'texture_glyph_review': '图片文字'}
EXPECTED = {'symbol_review': 42, 'existing_dimensions_review': 5, 'dynamic_template': 2, 'texture_glyph_review': 6}
CONTROL = re.compile(r'<<[^>]+>>|<\d+>|＜ｔｍ＞.*?＜／ｔｍ＞', re.S)

def digest(value):
    return hashlib.sha256(value).hexdigest()

def resolve(doc, pointer):
    for key in pointer.lstrip('/').split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        doc = doc[int(key)] if isinstance(doc, list) else doc[key]
    return doc

def boundaries(annotated, text):
    """Validate decision markup without permitting any change to source content."""
    parts = re.split(r'(\[\[|\]\])', annotated)
    output, spans, opened = '', [], None
    for part in parts:
        if part == '[[':
            if opened is not None:
                raise ValueError('收窄范围不可嵌套')
            opened = len(output)
        elif part == ']]':
            if opened is None or opened == len(output):
                raise ValueError('收窄范围未配对或为空')
            spans.append([opened, len(output)])
            opened = None
        else:
            output += part
    if opened is not None or output != text:
        raise ValueError('仅可调整 [[收窄范围]]，必须保留全部原文与控制语法')
    for start, end in spans:
        for token in CONTROL.finditer(text):
            if start < token.end() and end > token.start():
                raise ValueError('原生标记与动态模板必须留在收窄范围外')
    return spans

def annotate(text, spans):
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + '[[' + text[start:end] + ']]' + text[end:]
    return text

def propose(record, text):
    spans, cursor = [], 0
    for run in record['runs']:
        token = run['text']
        start = text.find(token, cursor)
        if start < 0:
            raise ValueError(f'Cannot locate run: {record}')
        end = start + len(token)
        cursor = end
        if start and text[start - 1] == '−':
            start -= 1
        if '／' in token:
            spans.extend([start + m.start(), start + m.end()] for m in re.finditer(r'\d+', token))
        else:
            spans.append([start, end])
    for m in re.finditer(r'Big O·Final Stage', text):
        spans = [s for s in spans if s[1] <= m.start() or s[0] >= m.end()]
        spans.append([m.start(), m.end()])
    status = record['status']
    if status == 'texture_glyph_review':
        reason = '保留文字内容，在图片字形和排版中调整高亮英文字段。当前图片仅供定位；确认后另做候选图片和游戏画面验证。'
        checks = '索引角色、透明度、CLUT、非目标像素、资产边界及实际绘制路径；AID 使用显式重制与重新冻结流程。'
    elif status == 'dynamic_template':
        reason = '仅收窄固定条件数字；完整保留 ＜ｔｍ＞击坠数＜／ｔｍ＞，动态击坠数不进入固定收窄范围。'
        checks = '核对原生模板绑定、展开上限及最长合法值，验证 100／150 架条件附近的自然运行画面。'
    elif status == 'existing_dimensions_review':
        reason = ('只收窄各档固定数字，分隔用全角斜线保留原宽；HP 两字符保持原宽。' if '10000' in text else '只收窄 TRI 或 EXP，保留按钮／图标相关原生标记及其位置。')
        checks = '校验原生控制序列逐字不变、按钮／图标显示、收窄后的状态恢复、字段容量和页面换回。'
    else:
        notes = []
        if '−' in text:
            notes.append('数值前的减号属于运算表达式，与数字及百分号一起收窄；无后续数字的减号保持原宽')
        if '—' in text:
            notes.append('拖长音或解释用破折号属于正文，保持原宽并留在收窄范围外')
        if 'Big O·Final Stage' in text:
            notes.append('名称内部中点属于完整英文名称，随 Big O·Final Stage 一起收窄')
        elif '·' in text:
            notes.append('中点作为混合名称、分项按键或呼喊节奏的分隔，保持原宽；只收窄达到门槛的英数字段')
        reason = '；'.join(notes) + '。'
        checks = '核对符号字形、英文及数值完整性、收窄状态恢复、显示面宽度与物理槽容量。'
    result = annotate(text, spans)
    boundaries(result, text)
    return result, reason, checks

def build(output):
    scope = json.loads((BASE / 'confirmed-scope/work-scope.json').read_text())
    for path, expected in scope['corpus_input_sha256'].items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise ValueError(f'请刷新源清单，文件已变化：{path}')
    output.mkdir(parents=True, exist_ok=True)
    rows, images, docs = [], {}, {}
    for record in scope['records']:
        if record.get('status') not in CATEGORIES or 'compact' not in record['queues']:
            continue
        path = record['path']
        if path not in docs:
            docs[path] = json.loads((ROOT / path).read_text())
        raw = resolve(docs[path], record['json_pointer'])
        text = raw.replace('\\n', '\n')
        parent = resolve(docs[path], record['json_pointer'].rsplit('/', 1)[0])
        proposal, reason, checks = propose(record, text)
        row = dict(record, key=digest((path + '#' + record['json_pointer']).encode())[:20],
                   text=text, raw=raw, source_sha256=digest(raw.encode()), proposal=proposal,
                   reason=reason, checks=checks,
                   japanese=(parent.get('source_text') or parent.get('source') or parent.get('original') or '') if isinstance(parent, dict) else '')
        if record['status'] == 'texture_glyph_review':
            family = record['id'].split('/')[0]
            if family in ('aid', 'tricmn'):
                config_path = f'config/assets/{"aid-battle-prompts" if family == "aid" else "tricmn-battle-overlays"}-zh.json'
                config = json.loads((ROOT / config_path).read_text())
                label = next(x for x in config['labels'] if x['entry_id'] == record['id'])
                image_path = f'work/review/{"aid-battle-prompts" if family == "aid" else "tricmn-battle-overlays"}-zh/localized.png'
                x, y, w, h = label['rect']
                y += label.get('picture_index', 0) * 256
                row['asset_location'] = f'{config_path} · picture {label.get("picture_index", 0)} · rect {label["rect"]}'
            else:
                image_path = 'work/build/zh-release-full-story/components/previews/world-map-titles/world-map-titles-contact-sheet.png'
                index = next(i for i, e in enumerate(docs[path]['entries']) if e['id'] == record['id'])
                x, y, w, h = 0, index * 36, 512, 32
                row['asset_location'] = f'MAPMODEL members {parent["members"]} · 既有标题图集第 {index + 1} 行'
            name = f'{family}.png'
            shutil.copyfile(ROOT / image_path, output / name)
            images[name] = {'path': image_path, 'sha256': digest((ROOT / image_path).read_bytes())}
            row['image'] = dict(url=name, x=x, y=y, width=w, height=h)
        rows.append(row)
    counts = dict(Counter(r['status'] for r in rows))
    assert counts == EXPECTED, counts
    assert len({r['key'] for r in rows}) == 55
    dataset = dict(schema=1, source_commit=scope['source_commit'], counts=counts, categories=CATEGORIES, rows=rows, images=images)
    dataset['fingerprint'] = digest(json.dumps(dataset, ensure_ascii=False, sort_keys=True).encode())
    (output / 'data.json').write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + '\n')
    shutil.copyfile(Path(__file__).with_name('special-confirmation.html'), output / 'index.html')
    return dataset

def serve(output, port):
    dataset = json.loads((output / 'data.json').read_text())
    records = {row['key']: row for row in dataset['rows']}
    state_path = output / 'decisions.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else dict(schema=1, fingerprint=dataset['fingerprint'], revision=0, decisions={})
    if state['fingerprint'] != dataset['fingerprint']:
        raise ValueError('清单已变化，旧决定仍保留；请另建审核目录或先核对旧决定')
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, payload, content_type='application/json; charset=utf-8'):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ('/api/state', '/api/export'):
                return self.reply(200, dict(state, rows=dataset['rows']) if path.endswith('export') else state)
            allowed = {'/': ('index.html', 'text/html; charset=utf-8'), '/index.html': ('index.html', 'text/html; charset=utf-8'), '/data.json': ('data.json', 'application/json; charset=utf-8')}
            allowed.update({'/' + name: (name, 'image/png') for name in dataset['images']})
            if path not in allowed:
                return self.reply(404, {'error': 'Not found'})
            name, content_type = allowed[path]
            self.reply(200, (output / name).read_bytes(), content_type)
        def do_POST(self):
            if self.path != '/api/decision':
                return self.reply(404, {'error': 'Not found'})
            if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                return self.reply(403, {'error': '仅接受本地审核页提交'})
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length < 100000:
                    raise ValueError('请求长度无效')
                request = json.loads(self.rfile.read(length))
                if request.get('fingerprint') != dataset['fingerprint'] or request.get('revision') != state['revision']:
                    return self.reply(409, {'error': '页面状态已更新，请刷新后继续；未覆盖现有决定'})
                key = request['key']
                row = records[key]
                decision = request['decision']
                if decision not in ('approved', 'custom', 'keep', 'defer', 'pending'):
                    raise ValueError('无效的决定')
                note = request.get('note', '')
                if not isinstance(note, str) or len(note) > 4000:
                    raise ValueError('备注长度无效')
                if decision in ('custom', 'defer') and not note.strip():
                    raise ValueError('请填写修改说明或暂缓原因')
                annotation = request.get('annotation', row['proposal']) if decision == 'custom' else row['proposal']
                if not isinstance(annotation, str):
                    raise ValueError('边界格式无效')
                spans = boundaries(annotation, row['text'])
                if digest(resolve(json.loads((ROOT / row['path']).read_text()), row['json_pointer']).encode()) != row['source_sha256']:
                    raise ValueError('源条目已变化，请重新核对后建立审核页')
                updated = json.loads(json.dumps(state))
                if decision == 'pending':
                    updated['decisions'].pop(key, None)
                else:
                    updated['decisions'][key] = dict(decision=decision, note=note,
                        annotation=annotation if decision in ('approved', 'custom') else None,
                        spans=spans if decision in ('approved', 'custom') else [],
                        source_sha256=row['source_sha256'], updated_at=datetime.now(timezone.utc).isoformat())
                updated['revision'] += 1
                temp = output / 'decisions.tmp'
                temp.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n')
                temp.replace(state_path)
                state.clear()
                state.update(updated)
                self.reply(200, state)
            except (KeyError, ValueError, TypeError, OSError) as error:
                self.reply(400, {'error': str(error)})
    print(f'http://127.0.0.1:{port}/ — {len(records)} records — {state_path}', flush=True)
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--serve-only', action='store_true')
    args = parser.parse_args()
    if not args.serve_only:
        data = build(args.output)
        print(json.dumps(dict(counts=data['counts'], output=str(args.output)), ensure_ascii=False))
    if not args.build_only:
        serve(args.output, args.port)
