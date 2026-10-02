"""Author prose candidates without treating old physical wraps as paragraphs."""
from __future__ import annotations

from dataclasses import dataclass, replace
from .chinese_layout import ChineseLayoutError, ChineseLayoutProfile, reflow_chinese_paragraph
from .renderer_metrics import text_extent
from .text import CONTROL_NOTATION
from .summary import validate_scroll_placeholders


@dataclass(frozen=True)
class ProseLayoutResult:
    text: str
    paragraph_count: int
    line_widths_px: tuple[int, ...]


def logical_prose_text(text: str) -> str:
    """Remove physical wraps and paragraph indentation, retaining internal spaces."""
    return ''.join(line.lstrip('　 ') for line in text.replace('\r','').split('\n'))


def reflow_chinese_prose(
    text: str, *, profile: ChineseLayoutProfile,
    protected_terms: tuple[str, ...] = (), maximum_lines: int | None = None,
) -> ProseLayoutResult:
    """Balance each authored paragraph; retain paragraph starts and blank rows.

    An indented physical row starts a paragraph. Unindented rows continue the
    preceding paragraph. This is an authoring operation, not an implicit change
    to fixed production fields or scrolling timing controls.
    """
    groups: list[tuple[str,str] | str] = []
    for line in text.replace('\r','').split('\n'):
        if not line.strip('　 '):
            groups.append(line)
            continue
        indent=line[:len(line)-len(line.lstrip('　 '))]
        body=line[len(indent):]
        if groups and isinstance(groups[-1],tuple) and not indent:
            old_indent,old_body=groups[-1]
            groups[-1]=(old_indent,old_body+body)
        else:
            groups.append((indent,body))
    lines=[]
    count=0
    for group in groups:
        if isinstance(group,str):
            # Preserve authored placeholders, including multi-space native
            # rows. MTV_PROS/MTZSPROS also need a glyph for an empty separator.
            scroll = profile.profile_id in ('world_history_scroll','sp_narration_scroll')
            lines.append(group.replace(' ','　') or ('　' if scroll else ''))
            continue
        indent,body=group
        count+=1
        candidate=replace(profile,line_count_mode='minimum',line_packing='balanced',
            maximum_lines=None,first_line_maximum_width=profile.maximum_width-len(indent))
        fitted=reflow_chinese_paragraph(body,profile=candidate,protected_terms=protected_terms)
        rows=fitted.text.split('\n')
        rows[0]=indent+rows[0]
        lines.extend(rows)
    if maximum_lines is not None and len(lines)>maximum_lines:
        raise ChineseLayoutError(f'prose exceeds {maximum_lines} physical rows: {len(lines)}')
    result='\n'.join(lines)
    if profile.profile_id in ('world_history_scroll','sp_narration_scroll'):
        validate_scroll_placeholders(text,result,label=profile.profile_id+' reflow')
    if logical_prose_text(result)!=logical_prose_text(text):
        raise ChineseLayoutError('prose reflow changed visible content')
    if CONTROL_NOTATION.findall(result) != CONTROL_NOTATION.findall(text):
        raise ChineseLayoutError('prose reflow changed controls or variables')
    state=None
    widths=[]
    for line in lines:
        extent=text_extent(line,default_advance_px=profile.default_advance_px,state=state)
        state=extent.state
        widths.append(extent.occupied_px)
        if extent.occupied_px>profile.maximum_width*profile.default_advance_px:
            raise ChineseLayoutError('prose exceeds pixel width including indentation')
    return ProseLayoutResult(result,count,tuple(widths))
