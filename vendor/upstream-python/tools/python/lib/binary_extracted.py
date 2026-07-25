import re
import struct
import pyjson5 as json
import string
import pandas as pd
from tools.python.lib.FileIO import FileIO

VALID_VOICEID = [r'(VSM_\w+)', r'(VCT_\w+)', r'(S\d+)', r'(C\d+)']
COMMON_TAG = r"(<[\w/]+:?\w+>)"
HEX_TAG = r"(\{[0-9A-F]{2}\})"
PRINTABLE_CHARS = "".join(
            (string.digits, string.ascii_letters, string.punctuation, " ")
        )
jsonTblTags = dict()
with open('project/tbl_all.json') as f:
    jsonraw = json.loads(f.read(), encoding="utf-8")
    for k, v in jsonraw.items():
        jsonTblTags[k] = {int(k2, 16): v2 for k2, v2 in v.items()}

ijsonTblTags = dict()
for k, v in jsonTblTags.items():
    if k in ['tags', 'tbl']:
        ijsonTblTags[k] = {v2: k2 for k2, v2 in v.items()}
    else:
        ijsonTblTags[k] = {v2: hex(k2).replace('0x', '').upper() for k2, v2 in v.items()}
iTags = {v2.upper(): k2 for k2, v2 in jsonTblTags['tags'].items()}


def bytes_to_text(src: FileIO, offset: int = -1, speaker:bool = False):
    finalText = ""
    chars = jsonTblTags['tbl']

    if (offset > 0):
        src.seek(offset, 0)
    buffer = b''
    while True:
        b = src.read(1)

        if b == b"\x00" or b == b'': break

        buffer += b
        b = ord(b)

        # Tags
        if b in [0x31, 0x32, 0x33, 0x34, 0x35]:

            if b in jsonTblTags['tags'].keys():
                tag_name = jsonTblTags['tags'].get(b)
            else:
                tag_name = hex(b).upper().replace('0X','')

            value = src.read(1).hex().upper()
            finalText += f"<{tag_name}:{value}>"
            continue

        # Custom Encoded Text
        if (0x80 <= b <= 0x9F) or (0xE0 <= b <= 0xEA):
            c = (b << 8) | src.read_uint8()
            finalText += chars.get(c, "{%02X}{%02X}" % (c >> 8, c & 0xFF))
            continue

        if b == 0x0A:

            if speaker:
                return finalText, buffer

            finalText += ("\n")
            continue

        # ASCII text
        if chr(b) in PRINTABLE_CHARS:
            finalText += chr(b)
            continue

        # cp932 text
        if 0xA0 < b < 0xE0:
            finalText += struct.pack("B", b).decode("cp932")
            continue



        finalText += "{%02X}" % b

    return finalText, buffer


def get_shift_equivalent(character:str):
    base = 33311
    b = ord(character.encode('cp932'))

    if character.isupper():
        return (b + base).to_bytes(2, 'big')

    else:
        return (b + base + 1).to_bytes(2, 'big')



def text_to_bytes(text:str, font_adjusted:bool):
    multi_regex = (HEX_TAG + "|" + COMMON_TAG + r"|(\n)")
    tokens = [sh for sh in re.split(multi_regex, text) if sh]
    output = b''
    percent_found = False

    dict_spec = {
        "≥": b'\x3F\x18',
        "Sky": b'\x81\xEC',
        "Ground": b'\x81\xED',
        "Water": b'\x81\xEE',
        "Space": b'\x81\xEF'
    }
    list_weird = []
    for t in tokens:
        # Hex literals
        if re.match(HEX_TAG, t):
            output += struct.pack("B", int(t[1:3], 16))

        # Control codes with the format of <XX> or <XX:XX>
        elif re.match(COMMON_TAG, t):
            tag, param, *_ = t[1:-1].split(":") + [None]

            # Tags like <XX>
            if tag in dict_spec.keys():
                output += dict_spec[tag]

            # Tags like <XX:XX>
            else:
                #Known control codes
                if tag in ['width', 'color', 'space', 'height']:
                    tag_int = ijsonTblTags['tags'][tag]
                else:
                    tag_int = int(tag, 16)

                output += bytes([tag_int])
                output += bytes([int(param,16)])

        # Line Break
        elif t == "\n":
            output += b"\x0A"

        else:
            for c in t:

                #Special Characters not in ASCII
                if c in dict_spec.keys():
                    output += dict_spec[c]

                #ASCII characters
                elif c in PRINTABLE_CHARS:

                    val = b''
                    if c >= '.' and c <= '?' and c != '%':

                        #Skip if % sign to see if we don't find %s
                        #%s is handled differently with the game and we dont want to add 0x3F
                        if c == '%':
                            percent_found = True

                        else:
                            val += b'\x3F'
                            val += c.encode("cp932")

                    elif percent_found:

                        #If we dont have a %s pattern, we add our 0x3F special control code
                        if c != 's':
                            val += b'\x3F'

                        val += c.encode("cp932")

                    else:
                        val += c.encode("cp932")



                    if not font_adjusted:
                        val = get_shift_equivalent(c)

                    output += val

                #Shift-Jis
                else:

                    if c in ijsonTblTags["tbl"].keys():
                        b = ijsonTblTags["tbl"][c].to_bytes(2, 'big')
                        output += b
                    else:
                        c = c.replace("\u200b", "")
                        output += c.encode("cp932")

    return output

def load_width_table(excel_path):
    """
    Excel format:
    Ascii | Width_0C (hex or int)
    """
    df = pd.read_excel(excel_path)

    df = df.dropna(subset=['Width_0C'])
    df = df[df['Width_0C'] != '']

    df['Width_0C'] = df['Width_0C'].apply(lambda x: int(x, 16))

    return dict(zip(df["Ascii"], df["Width_0C"]))


# =========================================================
# CLEAN INPUT STRING (SRWZ SAFE)
# =========================================================

import re

# =========================================================
# TOKENIZER (FAST + CONTROL AWARE)
# =========================================================

def tokenize(text):
    tokens = []
    buf = ""

    i = 0
    while i < len(text):
        c = text[i]

        # control code
        if c == "<":
            if buf:
                tokens.append(buf)
                buf = ""

            end = text.find(">", i)
            if end != -1:
                tokens.append(text[i:end + 1])
                i = end + 1
                continue

        buf += c

        # flush at space boundaries (but keep space in chunk)
        if c == " ":
            tokens.append(buf)
            buf = ""

        i += 1

    if buf:
        tokens.append(buf)

    return tokens


# =========================================================
# TOKEN TYPE HELPERS
# =========================================================

def is_control(token):
    return token.startswith("<") and token.endswith(">")


# =========================================================
# WIDTH CALCULATION
# =========================================================

def word_width(token, width_map):
    if is_control(token):
        return 0

    return sum(width_map.get(c, width_map.get("?", 8)) for c in token)


def compute_widths(tokens, width_map):
    return [word_width(t, width_map) for t in tokens]


# =========================================================
# FAST GREEDY BREAK (ENGINE-LIKE)
# =========================================================

def break_lines_greedy(text, width_map, max_width, max_lines=4):

    norm = normalize_text(text)
    tokens = tokenize(norm)
    widths = compute_widths(tokens, width_map)

    lines = []
    cur = []
    cur_w = 0

    for t, w in zip(tokens, widths):

        if cur_w + w > max_width and cur:
            lines.append(cur)
            cur = []
            cur_w = 0

            if len(lines) == max_lines - 1:
                break

        cur.append(t)
        cur_w += w

    if cur:
        lines.append(cur)

    return lines[:max_lines]


# =========================================================
# BALANCED LINE BREAK (FAST DP + PREFIX SUMS)
# =========================================================

def break_lines_dp(text, width_map, max_width, max_lines=4):

    tokens = tokenize(text)
    n = len(tokens)

    if n == 0:
        return []

    widths = compute_widths(tokens, width_map)

    # prefix sums
    prefix = [0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + widths[i]

    def range_width(i, j):
        return prefix[j] - prefix[i]

    INF = float("inf")

    dp = [[INF] * (max_lines + 1) for _ in range(n + 1)]
    nxt = [[-1] * (max_lines + 1) for _ in range(n + 1)]

    dp[n][0] = 0

    for i in range(n - 1, -1, -1):
        dp[n][0] = 0
        for k in range(1, max_lines + 1):

            best = INF
            best_j = -1

            for j in range(i + 1, n + 1):

                w = range_width(i, j)

                if w > max_width:
                    break

                # lightweight scoring (SRWZ-like heuristic)
                score = abs(w - max_width) + dp[j][k - 1]

                if score < best:
                    best = score
                    best_j = j

            dp[i][k] = best
            nxt[i][k] = best_j

    # reconstruct
    result = []
    i = 0
    k = max_lines

    while i < n and k > 0:
        j = nxt[i][k]
        if j == -1:
            break
        result.append(tokens[i:j])
        i = j
        k -= 1

    if not result:
        return [tokens]

    return result

def normalize_text(text):
    # STEP 1: temporarily protect ellipses
    text = text.replace("...", "\uFFF0")  # private-use placeholder

    # STEP 2: add space after single dots (but not already spaced)
    text = re.sub(r'\.(?=\S)', '. ', text)

    # STEP 3: restore ellipses
    text = text.replace("\uFFF0", "...")

    # STEP 4: ensure only ONE space after ellipsis
    text = re.sub(r'\.\.\.(?=\S)', '... ', text)

    return text

# =========================================================
# MAIN API
# =========================================================

def linebreak(text, width_map, min_width, max_width, max_lines=4, mode="dp"):
    """
    SRWZ linebreaking engine.

    mode:
      - "dp"     → balanced layout (recommended)
      - "greedy" → fastest (engine-like)
    """

    text = clean_string(text)

    if mode == "greedy":
        lines = break_lines_greedy(text, width_map, max_width, max_lines)
    else:
        lines = break_lines_dp(text, width_map, max_width, max_lines)

        # HARD VALIDATION
        if not lines or len(lines) == 1:
            return break_lines_greedy(text, width_map, max_width, max_lines)

    # enforce minimum width constraint
    def line_width(line):
        return sum(word_width(t, width_map) for t in line)

    valid = [l for l in lines if line_width(l) >= min_width]

    return valid if valid else lines
