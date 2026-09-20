"""Character-aware Q&A layout shared by Original, The Best and Special Disc.

All visible characters carry their original colour and z value across record
splits. Page allocations and sprite payloads remain the responsibility of the
caller; pack_page checks the allocation budget and two-byte text round trip.
"""
from collections import defaultdict
import re
import struct
from .text import decode_text, two_byte_visible_spaces


def require(condition, message):
    if not condition:
        raise ValueError(message)


# Runtime Q&A scissor hides the glyph at x=532 (e.g. page 102's period
# and the first character of 具体). x=513 is the last fully visible cell.
MAX_X = 513
CLOSE = set('。，、；：！？”’」』）】》〉,.;:!?%％')
OPEN = set('“‘「『（【《〈')
ATOMIC = re.compile(r'[LR][12]|[A-Za-z]+|[0-9]+(?:[.．][0-9]+)*(?:[～〜~][0-9]+)?(?:[%％]|倍|级|段|机|格|回合|人|种|次|键)?')
PROTECTED = ('SR点数', '小队攻击', 'TRI攻击', 'MAP兵器', '格斗武器', '伤害比例',
             '精神指令', '援护攻击', '援护防御', '全体攻击', '命中率', '回避率',
             '驾驶员', '移动力', '机体', '小队', '提升伤害', '最高值', '修理', '补给',
             '小队加成', '集中阵型', '分散阵型', 'TRI阵型', '特殊能力', '修理装置',
             '补给装置', '中途存档', '软复位', '快速读档', '△键', '○键', '□键')


def legal_break(text, at, *, shared_boundary=False, protected_terms=None):
    if at <= 0 or at >= len(text):
        return True
    if text[at] in CLOSE or text[at - 1] in OPEN:
        return False
    if not shared_boundary and (text[at] in ' \u3000' or text[at-1] in ' \u3000'):
        return False
    for match in ATOMIC.finditer(text):
        if match.start() < at < match.end():
            return False
    terms = protected_terms if protected_terms is not None else (('SR点数',) if shared_boundary else PROTECTED)
    for token in terms:
        for match in re.finditer(re.escape(token), text):
            if match.start() < at < match.end():
                return False
    return True


def split_glyphs(glyphs, capacity, *, protected_terms=None):
    if len(glyphs) <= capacity:
        return glyphs, []
    text = ''.join(g[0] for g in glyphs)
    at = capacity
    if len(glyphs) - at < 4:
        at = max(1, len(glyphs) - 4)
    while at > 0 and not legal_break(text, at, protected_terms=protected_terms):
        at -= 1
    require(at > 0, f'Unbreakable Q&A token exceeds row capacity: {text}')
    return glyphs[:at], glyphs[at:]


def emit(glyphs, x, y, advance=19):
    records = []
    for char, style, z in glyphs:
        if records and records[-1]['style'] == list(style) and records[-1]['position'][2] == z:
            records[-1]['text'] += char
        else:
            records.append(dict(text=char, style=list(style), position=[x, y, z]))
        x += advance
    return records


def flow(runs, first_x, continuation_x, y):
    glyphs = [(c, tuple(r['style']), 1) for r in runs for c in r['text']]
    records = []
    x = first_x
    while glyphs:
        row, glyphs = split_glyphs(glyphs, (MAX_X - x) // 19 + 1)
        records.extend(emit(row, x, y))
        if glyphs:
            y += 11
            x = continuation_x
    return records, y


def styled_runs(records):
    runs = []
    for r in records:
        if not r['text']:
            continue
        key = (*r['style'], r['position'][2])
        text = two_byte_visible_spaces(r['text'])
        if runs and runs[-1][0] == key:
            runs[-1] = (key, runs[-1][1] + text)
        else:
            runs.append((key, text))
    return runs


def shared_records(parsed, runtime):
    return [dict(text=decode_text(r['raw'] + b'\0', 0, runtime).text,
                 style=[r['style0'], r['style1']], position=[r['x'], r['y'], r['z']])
            for r in parsed['records']]


def repair_shared(records, *, preserve_table_continuation=False, protected_terms=None):
    """Repair illegal adjacent row boundaries; leave unaffected rows/columns exact.

    Colour is carried by each character, independent of its record. A repair
    can add positioned records but cannot change the ordered styled text.
    """
    def legal(text, at, *, shared_boundary=False):
        return legal_break(text, at, shared_boundary=shared_boundary,
                           protected_terms=protected_terms)

    def split(glyphs, capacity):
        return split_glyphs(glyphs, capacity, protected_terms=protected_terms)

    def continuation_x(left, fallback):
        if not preserve_table_continuation or left[0]["style"] != [2, 14]:
            return fallback
        # Colour records within a prose cell are contiguous. A real gap
        # identifies the next table column; overflow stays under that column.
        anchors = [b['position'][0] for a, b in zip(left, left[1:])
                   if b['position'][0] <= 266 and
                   b['position'][0] - (a['position'][0]+len(a['text'])*19) >= 19]
        return anchors[-1] if anchors else fallback

    rows = defaultdict(list)
    for r in records:
        if r['text']:
            rows[r['position'][1]].append(r)
    rows = [sorted(rs, key=lambda r: r['position'][0]) for _, rs in sorted(rows.items())]
    repairs = []
    # First repair runtime clipping. Keep retained column anchors, and carry
    # the clipped tail into a contiguous prose row when available.
    i = 0
    while i < len(rows):
        left = rows[i]
        positions = [r['position'][0]+j*19 for r in left for j in range(len(r['text']))]
        if left[0]['style'][0] == 4 or max(positions) <= MAX_X:
            i += 1
            continue
        lt = ''.join(r['text'] for r in left)
        right = rows[i+1] if i+1 < len(rows) else []
        join_next = bool(right and right[0]['position'][1]-left[0]['position'][1] == 11 and
            all(a['position'][0]+len(a['text'])*19 == b['position'][0] for a,b in zip(right,right[1:])))
        rt = ''.join(r['text'] for r in right) if join_next else ''
        cut = next(j for j,x in enumerate(positions) if x > MAX_X)
        if len(lt)-cut+len(rt) < 4:
            cut = max(1,len(lt)+len(rt)-4)
        while cut > 0 and not legal(lt+rt,cut):
            cut -= 1
        require(cut > 0,'Q&A clipped table cell cannot be reflowed')
        new_left,remaining = [],cut
        for r in left:
            if remaining <= 0:break
            take = min(remaining,len(r['text']))
            new_left.append(dict(r,text=r['text'][:take]));remaining -= take
        all_records = left + (right if join_next else [])
        glyphs = [(c,tuple(r['style']),r['position'][2]) for r in all_records for c in r['text']][cut:]
        x = min(left[0]['position'][0],right[0]['position'][0]) if join_next else left[0]['position'][0]
        x = continuation_x(left, x)
        y = left[0]['position'][1]+11;new_rows=[]
        while glyphs:
            line,glyphs = split(glyphs,(MAX_X-x)//19+1)
            new_rows.append(emit(line,x,y));y += 11
        consumed = 2 if join_next else 1
        delta = (1+len(new_rows)-consumed)*11
        for subsequent in rows[i+consumed:]:
            for r in subsequent:r['position']=[r['position'][0],r['position'][1]+delta,r['position'][2]]
        rows[i:i+consumed] = [new_left]+new_rows
        repairs.append(dict(kind='runtime_right_edge',y=left[0]['position'][1],before=[lt,rt],
                            after=[''.join(r['text']for r in row)for row in [new_left]+new_rows]))
        i += 1
    i = 0
    while i + 1 < len(rows):
        left, right = rows[i:i+2]
        ly, ry = left[0]['position'][1], right[0]['position'][1]
        lt, rt = [''.join(r['text'] for r in rs) for rs in (left, right)]
        # Table headings / list items can be consecutive independent rows.
        # Only repairs with punctuation, a split Latin run or a numeric unit
        # are accepted; no cross-paragraph joining.
        if ly < 20 or ry - ly != 11 or legal(lt + rt, len(lt), shared_boundary=True):
            i += 1
            continue
        glyphs = [(c, tuple(r['style']), r['position'][2]) for r in left + right for c in r['text']]
        # Prefer attaching closing punctuation without moving existing text.
        cut = len(lt)
        while cut < len(glyphs) and glyphs[cut][0] in CLOSE:
            cut += 1
        end_x = left[-1]['position'][0] + len(left[-1]['text']) * 19
        if (protected_terms is not None and end_x + (len(rt)-1)*19 <= MAX_X
                and all(a['position'][0]+len(a['text'])*19 == b['position'][0]
                        for a, b in zip(right, right[1:]))):
            # A short prose continuation can fit in the remaining cell width.
            # Join it whole instead of leaving a one-word remainder below.
            cut = len(glyphs)
        if cut == len(lt) or end_x + (cut - len(lt) - 1) * 19 > MAX_X:
            cut = len(lt) - (4 if len(rt) <= 2 else 1)
            while cut > 0 and not legal(lt + rt, cut):
                cut -= 1
        require(cut > 0 and legal(lt + rt, cut), 'Cannot repair Q&A boundary')
        # Preserve positions (including real table gaps) of the retained prefix.
        new_left, remaining = [], cut
        for r in left:
            if remaining <= 0:
                break
            take = min(remaining, len(r['text']))
            new_left.append(dict(r, text=r['text'][:take]))
            remaining -= take
        if cut > len(lt):
            new_left.extend(emit(glyphs[len(lt):cut], end_x, ly))
        x = min(left[0]['position'][0], right[0]['position'][0])
        x = continuation_x(left, x)
        tail, new_rows, y = glyphs[cut:], [], ry
        while tail:
            line, tail = split(tail, (MAX_X-x)//19+1)
            new_rows.append(emit(line, x, y))
            y += 11
        delta = (len(new_rows)-1)*11
        for subsequent in rows[i+2:]:
            for r in subsequent:
                r['position'] = [r['position'][0], r['position'][1]+delta, r['position'][2]]
        rows[i:i+2] = [new_left] + new_rows
        repairs.append(dict(y=ly, before=[lt,rt], after=[''.join(r['text'] for r in row) for row in [new_left]+new_rows]))
        i += 1
    result = [r for rs in rows for r in rs]
    require(styled_runs(result) == styled_runs(records), 'Shared Q&A styled text changed')
    return (result if repairs else records), repairs


def validate_records(records):
    rows = defaultdict(list)
    for r in records:
        if not r['text']:
            continue
        x,y,z = r['position']
        advance = 23 if r['style'][0] == 4 else 19
        require(x + (len(r['text'])-1)*advance <= MAX_X, 'Q&A width overflow')
        require(0 <= y < 65536 and z == 1, 'Q&A position invalid')
        rows[y].append(r)
    for y, rs in rows.items():
        rs.sort(key=lambda r:r['position'][0])
        for a,b in zip(rs,rs[1:]):
            advance = 23 if a['style'][0] == 4 else 19
            require(a['position'][0]+len(a['text'])*advance <= b['position'][0], 'Q&A overlap')
        if y >= 20:
            require(rs[0]['text'][0] not in CLOSE, 'Q&A leading punctuation')
            require(rs[-1]['text'][-1] not in OPEN, 'Q&A trailing opening punctuation')


def pack_page(parsed, records, encoder, runtime):
    body = bytearray()
    for r in records:
        raw = encoder.encode(two_byte_visible_spaces(r['text']), terminate=True)
        require(decode_text(raw, 0, runtime).text == two_byte_visible_spaces(r['text']), 'Q&A glyph readback mismatch')
        require(len(raw[:-1]) % 2 == 0 and b'\x20' not in raw[:-1], 'Q&A raw one-byte space/text')
        body += struct.pack('<BBHHH', *r['style'], *r['position']) + raw
    payload = struct.pack('<H', len(body)) + body + struct.pack('<H', parsed['sprite_size']) + parsed['sprite_bytes']
    require(len(payload) <= parsed['size'], f"Q&A allocation overflow: {len(payload)} > {parsed['size']}")
    return bytes(payload) + bytes(parsed['size'] - len(payload)), parsed['size'] - len(payload)
