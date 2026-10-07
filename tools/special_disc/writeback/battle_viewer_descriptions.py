"""Preserve the battle viewer's native name substitution, not a visible ※ glyph."""
NAME_CODE = 0x81A6


def uses_name_marker(target, source):
    return (target.startswith('sd/compdata/') and
            0x98730 <= int(target.rsplit('/', 1)[1], 16) <= 0x9E4E0 and
            '※' in source)


def description_overrides(target, source, translation, overrides):
    if not uses_name_marker(target, source):
        return overrides
    if source.count('※') != translation.count('※'):
        raise ValueError(f'battle viewer name substitution count changed: {target}')
    return {**overrides, '※': NAME_CODE}


def verify_name_marker(raw, target, source, translation):
    if not uses_name_marker(target, source):
        return 0
    count = source.count('※')
    # Walk stored codes so neither a newline nor a control parameter can be
    # confused with a glyph, and byte pairs spanning two glyphs never count.
    at, native_count = 0, 0
    while at < len(raw):
        code = raw[at]
        at += 1
        if code == 0:
            break
        if 0x31 <= code <= 0x35:
            at += 1
        elif 0x80 <= code <= 0x9F or 0xE0 <= code <= 0xEA:
            if at >= len(raw):
                raise ValueError('battle viewer truncated glyph')
            native_count += code * 256 + raw[at] == NAME_CODE
            at += 1
    if translation.count('※') != count or native_count != count:
        raise ValueError(f'battle viewer native name substitution changed: {target}')
    return count
