"""Prepare the AI inpainting kit for SP Disc images whose text sits on artwork.

Each job gets source.png, mask.png (white = Japanese text to remove), an
overlay preview and 4x copies for AI tools. The page and manifest describe
what to hand back. Inputs are read-only previews already exported under
work/analysis; nothing is written outside this directory.
"""
from __future__ import annotations

import base64
import html
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
TD = ROOT / "work/analysis/sp-texture-diff-20260912"
AID = ROOT / "work/analysis/sp-aiddata-images-20260912/images"
CHANGES = json.loads((TD / "comparison.json").read_text())["changes"]


def diff_png(index: int) -> Path:
    return TD / CHANGES[index]["sp_preview"]["file"]


def luma(p) -> int:
    r, g, b = p[:3]
    return (r * 299 + g * 587 + b * 114) // 1000


def detect_bbox(im: Image.Image, region, predicate, pad: int):
    """Bounding box of pixels satisfying predicate inside region, padded."""
    x0, y0, x1, y1 = region
    px = im.load()
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            p = px[x, y]
            if p[3] > 16 and predicate(p):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (max(x0, min(xs) - pad), max(y0, min(ys) - pad), min(x1, max(xs) + 1 + pad), min(y1, max(ys) + 1 + pad))


def mask_image(size, boxes) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for b in boxes:
        d.rectangle([b[0], b[1], b[2] - 1, b[3] - 1], fill=255)
    return m


def overlay(src: Image.Image, mask: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", src.size, (40, 44, 52, 255))
    bg.alpha_composite(src)
    red = Image.new("RGBA", src.size, (255, 40, 40, 0))
    red.putalpha(mask.point(lambda v: 110 if v else 0))
    bg.alpha_composite(red)
    edge = mask.filter(ImageFilter.FIND_EDGES)
    outline = Image.new("RGBA", src.size, (255, 230, 0, 0))
    outline.putalpha(edge.point(lambda v: 255 if v else 0))
    bg.alpha_composite(outline)
    return bg


jobs = []
# Confirmed by the user on 2026-09-17: simple backgrounds, painted out by local_paint.py.
LOCAL_PAINT = {"hsfc-chart-title-sp", "nisv-sound-select-title", "aid-banner-3", "aid-banner-5"}
# Text-free art found in the game (find_banner_sources_sift.py); rebuilt by rebuild_banner1.py.
SOURCE_REBUILD = {"aid-banner-1"}
# Same banner as the main game's localized 剧情流程; retitled by rebuild_hsfc105.py (user, 2026-09-17).
MAIN_RECIPE = {"hsfc-chart-title-z"}


# The user supplied text-free plates (buttons, heading) or finished Chinese banners (2, 4).
USER_PLATE = {"heading-plate"}
# The buttons are drawn whole from the user's plate (render_buttons.py; user, 2026-09-18).
BUTTON_PLATE = {"vt1-16-title-menu", "vt1-30-extra-stage-menu", "vt1-53-battle-viewer-menu"}
AI_FINAL = {"aid-banner-2", "aid-banner-4"}
# The title logo's subtitle band: rim and glow fitted from the Japanese art (retitle_logo.py).
LOGO_REBUILD = {"vt1-28-logo"}
HOW = {
    "user_plate": "用你提供的无字底板；按格对齐，只补文字处，其余保留原图；文字效果按状态从原图拟合；项目字体。",
    "button_plate": "整块按钮直接用你提供的无字底板（五种状态，按原按钮轮廓对齐，边框统一取灰色态）；中文按像素网格对齐并加粗 0.25 像素，效果按状态从原图拟合；项目字体；图集换一套新调色板。",
    "ai_final": "你用 AI 做好的中文横幅；按原图对齐，只替换标题附近，量化到本张的调色板组。",
    "source_rebuild": "游戏内原图（KVMDATA 偏移 0x25C4C0）重建底图；文字层样式由原图拟合；项目字体。",
    "main_recipe": "沿用本篇“剧情流程”的做法（先逐字节复现本篇锁定结果）；普通和高亮两种状态都正确。",
    "local_paint": "局部涂抹的底图；样式取自特别篇原图；项目字体。",
    "logo_rebuild": "从日文原图拟合描边与光晕，条内重排中文，右上角的拷贝同步写回；项目字体。",
}


def method_of(slug: str) -> str:
    if slug in SOURCE_REBUILD:
        return "source_rebuild"
    if slug in MAIN_RECIPE:
        return "main_recipe"
    if slug in BUTTON_PLATE:
        return "button_plate"
    if slug in USER_PLATE:
        return "user_plate"
    if slug in AI_FINAL:
        return "ai_final"
    if slug in LOGO_REBUILD:
        return "logo_rebuild"
    return "local_paint" if slug in LOCAL_PAINT else "ai_inpaint"


def add_job(slug, title, src_path, boxes, *, target, fmt, texts, style, note="", reuse_for=None):
    src = Image.open(src_path).convert("RGBA")
    mask = mask_image(src.size, boxes)
    folder = OUT / "jobs" / slug
    folder.mkdir(parents=True, exist_ok=True)
    src.save(folder / "source.png")
    mask.save(folder / "mask.png")
    overlay(src, mask).save(folder / "overlay.png")
    w, h = src.size
    src.resize((w * 4, h * 4), Image.LANCZOS).save(folder / "source@4x.png")
    mask.resize((w * 4, h * 4), Image.NEAREST).save(folder / "mask@4x.png")
    jobs.append({
        "slug": slug, "title": title, "method": method_of(slug),
        "size": [w, h], "target": target, "format": fmt,
        "mask_boxes": [list(b) for b in boxes], "texts": texts, "style": style,
        "note": note, "reuse_for": reuse_for or [],
    })


# ---------------------------------------------------------------- button atlases
COLS = [(3, 252), (259, 508)]
CELL_W, CELL_H = 249, 39


def button_boxes(im: Image.Image):
    """Per-label text span from the grey state's dark glyph columns, reused for all 5 states."""
    px = im.load()
    boxes = []
    for x0, _x1 in COLS:
        for label_row in range(2):
            y0 = 1 + label_row * 5 * 40
            xs = [x for x in range(x0 + 24, x0 + 234)
                  if sum(1 for y in range(y0 + 9, y0 + 31) if luma(px[x, y]) < 30) >= 2]
            if not xs:
                raise SystemExit("button label not found")
            right = max(xs)
            # Thin trailing long-vowel bars (ー) are lighter; follow them along the glyph middle.
            miss, x = 0, right + 1
            while x <= x0 + 228 and miss < 4:
                if any(luma(px[x, y]) < 50 for y in range(y0 + 15, y0 + 24)):
                    right, miss = x, 0
                else:
                    miss += 1
                x += 1
            left, right = min(xs) - 4, right + 5
            for state in range(5):
                top = y0 + state * 40
                boxes.append((left, top + 4, right, top + 32))
    return boxes


BUTTON_STYLE = "5 个状态从上到下：灰色未选、浅绿、更浅（字淡）、亮绿（字几乎看不见）、深绿；字为粗黑体，灰色态黑字白描边，绿色各态为同色系浮雕效果"
atlases = [
    ("vt1-16-title-menu", "VT1 块16 #156 标题菜单按钮图集", 156,
     [("エクストラステージ", "额外关卡", "已确认"), ("ライブラリー", "资料库", "沿用本篇"),
      ("スペシャルシアター", "特别剧场", "已确认"), ("バトルビューワー", "战斗鉴赏", "已确认")], ""),
    ("vt1-30-extra-stage-menu", "VT1 块30 #171 额外关卡按钮图集", 171,
     [("ストーリーモード", "剧情模式", "已确认"), ("チャレンジバトル", "挑战模式", "已确认"),
      ("ロード", "读取", "沿用本篇"), ("コンティニュー", "继续", "沿用本篇")],
     "原图第 4 行（亮绿状态）的第一格残留了「スペシャルシアター」字样，原版如此，按“剧情模式”处理即可"),
    ("vt1-53-battle-viewer-menu", "VT1 块53 #185 战斗演出鉴赏按钮图集", 185,
     [("ノーマル", "普通", "沿用本篇 Q&A"), ("シンプル", "简易", "待定"),
      ("トライ", "TRI", "沿用本篇 TRI 写法"), ("シングル", "单机", "待定")], ""),
]
for slug, title, idx, labels, note in atlases:
    im = Image.open(diff_png(idx)).convert("RGBA")
    add_job(slug, title, diff_png(idx), button_boxes(im),
            target=f"DATA/VT1.BIN {CHANGES[idx]['sp']['location']}",
            fmt="512×512 PSMT8，单一 256 色调色板；2 列×10 行，每格 249×39，每个按钮 5 种状态",
            texts=[{"ja": ja, "zh": zh, "status": st} for ja, zh, st in labels],
            style=BUTTON_STYLE, note=note)

# ---------------------------------------------------------------- heading plate (shared by 5)
head = Image.open(diff_png(173)).convert("RGBA")
hb = detect_bbox(head, (40, 8, 400, 50), lambda p: luma(p) > 185, pad=5)
add_job("heading-plate", "模式标题共用底板（以 VT1 #173 为底）", diff_png(173), [hb],
        target="DATA/VT1.BIN 块36、38、45、57 与 AID_DATA/AIDDATA.BIN 块2 标题（5 张 512×64 PSMT8）",
        fmt="512×64 PSMT8；金属底板位于 x 4–419、y 5–51，底纹有淡色英文 “Super Robot Wars Z Special Disc”",
        texts=[
            {"ja": "エクストラステージ", "zh": "额外关卡", "status": "已确认"},
            {"ja": "ストーリーモード", "zh": "剧情模式", "status": "已确认"},
            {"ja": "チャレンジバトル", "zh": "挑战模式", "status": "已确认"},
            {"ja": "バトルビューワー", "zh": "战斗鉴赏", "status": "已确认"},
            {"ja": "スペシャルシアター", "zh": "特别剧场", "status": "已确认"},
        ],
        style="浅灰白色粗黑体，深色描边，左对齐于底板中部",
        note="5 张标题的底板在文字区之外逐像素相同，只需修出 1 张无字底板，5 个中文标题都由构建流程写到这张底板上",
        reuse_for=["VT1 #173", "VT1 #175", "VT1 #180", "VT1 #187", "AIDDATA 块2 标题"])

# ---------------------------------------------------------------- AIDDATA banners
banner_names = [("中断メッセージ集", "中断对话合集", "已确认"), ("ムービー集", "影片集", "已确认"),
                ("設定資料集", "设定资料集", "待定"), ("バトルシアター", "战斗剧场", "已确认"),
                ("壁紙一覧", "壁纸一览", "待定")]
BANNER_STYLE_DARK = "黑色粗黑体，外围浅色发光；黑色下划线从文字左侧约 40 像素处延伸到横幅右端"
BANNER_STYLE_LIGHT = "白色粗黑体，深色阴影发光；白色下划线从文字左侧延伸到横幅右端"
# Text boxes checked by eye: the artwork itself has white areas, so brightness
# detection over-reaches on banners 2-4.
banner_boxes = [(272, 24, 566, 73), (378, 26, 569, 72), (352, 26, 569, 72), (358, 26, 603, 72), (354, 26, 606, 74)]
for k, (ja, zh, status) in enumerate(banner_names):
    path = AID / f"block-002-tim2-01-picture-{k:02d}.png"
    b = banner_boxes[k]
    add_job(f"aid-banner-{k + 1}", f"AIDDATA 块2 特别剧场横幅 {k + 1}", path, [b],
            target=f"AID_DATA/AIDDATA.BIN 块2 记录1 图{k}（调色板组 {k}）",
            fmt="1024×128 PSMT8，横幅在 x 0–619、y 1–77；5 张共用一个调色板文件，每张用各自的 256 色组",
            texts=[{"ja": ja, "zh": zh, "status": status}],
            style=BANNER_STYLE_LIGHT if k == 4 else BANNER_STYLE_DARK,
            note="每张底图是不同的插画，需要各自修补；游戏内只有横幅 1 找到了无字原图")

# ---------------------------------------------------------------- NISV / HSFC
im = Image.open(diff_png(128)).convert("RGBA")
b = detect_bbox(im, (5, 0, 222, 40), lambda p: luma(p) > 225, pad=3)
add_job("nisv-sound-select-title", "NISVDATA #128 声音选择标题", diff_png(128), [b],
        target=f"DATA/NISVDATA.BIN 块1 {CHANGES[128]['sp']['location']}",
        fmt="512×256 PSMT8；只处理左上角橙棕色横幅（x 0–226、y 0–40），其余部件保持原样",
        texts=[{"ja": "サウンドセレクト", "zh": "音乐选择", "status": "沿用本篇"}],
        style="白色粗黑体，深棕色描边",
        note="本篇同名标题已汉化，但特别篇换了底框颜色和箭头")

im = Image.open(diff_png(105)).convert("RGBA")
b = detect_bbox(im, (10, 192, 280, 236), lambda p: luma(p) > 195, pad=4)
add_job("hsfc-chart-title-z", "HSFC #105 「シナリオチャート Z」", diff_png(105), [b],
        target=f"DATA/HSFC.BIN 块1 {CHANGES[105]['sp']['location']}",
        fmt="512×256 PSMT8，两组 256 色调色板（预览用第 0 组）；只处理左下角蓝色横幅（x 1–290、y 192–236）",
        texts=[{"ja": "シナリオチャート Z", "zh": "剧情流程 Z", "status": "沿用本篇（Z 保留）"}],
        style="浅青色字、深色描边（第 1 组调色板）；高亮状态为米黄底黑字（第 2 组调色板）",
        note="与本篇“剧情流程”横幅相同，按本篇做法完成，不需要 AI")

im = Image.open(diff_png(110)).convert("RGBA")
b = detect_bbox(im, (8, 448, 360, 492), lambda p: luma(p) > 215, pad=4)
add_job("hsfc-chart-title-sp", "HSFC #110 「シナリオチャート Special Disc」", diff_png(110), [b],
        target=f"DATA/HSFC.BIN 块1 {CHANGES[110]['sp']['location']}",
        fmt="512×512 PSMT8；只处理左下角橙红横幅（x 0–400、y 448–492），上方金属背景保持原样",
        texts=[{"ja": "シナリオチャート Special Disc", "zh": "剧情流程 Special Disc", "status": "沿用本篇（英文保留）"}],
        style="白色粗黑体，深色描边；英文 Special Disc 字号较小")

# ---------------------------------------------------------------- title logo subtitle band
# Added 2026-09-18 at the user's request; retitle_logo.py rebuilt it and also wrote the previews.
import retitle_logo as logo  # noqa: E402

(logo_pictures, logo_banks) = logo.load_record()
logo_folder = OUT / "jobs" / "vt1-28-logo"
logo_folder.mkdir(parents=True, exist_ok=True)
Image.fromarray(logo.composite(logo_pictures[0], logo_pictures[1], logo_banks)).save(logo_folder / "source-composite.png")
add_job("vt1-28-logo", "VT1 块 28 标题 logo 的副标题条", logo_folder / "source-composite.png",
        [(26, 17, 334, 49), (345, 0, 512, 66)],
        target=f"DATA/VT1.BIN 块28 {CHANGES[162]['sp']['location']}（图 0 画面、图 1 光晕）",
        fmt="512×256 PSMT4 三张图共用一组 64 色调色板（4 组 16 色，第几张用第几组）；预览为画面叠在光晕上",
        texts=[{"ja": "スペシャルディスク", "zh": "特别篇", "status": "待定"}],
        style="黄色斜体字，橙色描边，下方另有一层橙色光晕",
        note="右上角那块是条内文字的拷贝，游戏会把它切成两半叠回条上（等于画两遍），两处必须一致")

# ---------------------------------------------------------------- page + manifest
(OUT / "manifest.json").write_text(json.dumps({
    "schema_version": 1,
    "created": "2026-09-17",
    "purpose": "SP Disc images whose Japanese text sits on artwork: the text is removed (AI, local paint or in-game source art), the build renders Chinese",
    "return_file": "jobs/<slug>/clean.png",
    "local_paint_script": "local_paint.py",
    "source_rebuild_script": "rebuild_banner1.py",
    "main_recipe_script": "rebuild_hsfc105.py",
    "logo_rebuild_script": "retitle_logo.py",
    "jobs": jobs,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def on_dark(im: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", im.size, (46, 50, 58, 255))
    bg.alpha_composite(im.convert("RGBA"))
    return bg


def stack(images) -> Image.Image:
    out = Image.new("RGBA", (max(i.width for i in images), sum(i.height for i in images) + 4 * (len(images) - 1)), (30, 32, 38, 255))
    y = 0
    for i in images:
        out.paste(i, (0, y))
        y += i.height + 4
    return out


def finished_previews(slug: str) -> tuple[str, str]:
    """Write jobs/<slug>/preview-ja.png and preview-zh.png (Japanese vs current Chinese)."""
    folder = OUT / "jobs" / slug
    if slug == "aid-banner-1":
        box = (0, 0, 620, 78)
        ja = [Image.open(folder / "source.png").crop(box)]
        zh = [Image.open(folder / "final-zh.png").crop(box)]
    elif slug == "hsfc-chart-title-z":
        box = (0, 188, 300, 242)
        ja = [Image.open(folder / "source.png").crop(box), Image.open(folder / "source-bank1.png").crop(box)]
        zh = [Image.open(folder / "final-zh.png").crop(box), Image.open(folder / "final-zh-bank1.png").crop(box)]
    else:
        raise KeyError(slug)
    scale = 2
    for name, images in (("preview-ja.png", ja), ("preview-zh.png", zh)):
        sheet = stack([on_dark(i) for i in images])
        sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST).save(folder / name)
    return f"jobs/{slug}/preview-ja.png", f"jobs/{slug}/preview-zh.png"


CSS = """
:root{--bg:#f6f7f9;--fg:#1d2330;--muted:#5b6475;--card:#fff;--line:#dfe3ea;--accent:#b4531b;--chip:#eef1f5;--pend:#8a5300;--pend-bg:#fff1dc;--ok:#1f6b3a;--ok-bg:#e3f5e8}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15171b;--fg:#e7e9ee;--muted:#a3aab8;--card:#1e2126;--line:#30343c;--accent:#f0a060;--chip:#2a2e35;--pend:#ffd08a;--pend-bg:#46330f;--ok:#9be3b0;--ok-bg:#173a24}}
:root[data-theme="dark"]{--bg:#15171b;--fg:#e7e9ee;--muted:#a3aab8;--card:#1e2126;--line:#30343c;--accent:#f0a060;--chip:#2a2e35;--pend:#ffd08a;--pend-bg:#46330f;--ok:#9be3b0;--ok-bg:#173a24}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}h1{font-size:24px;margin:0 0 8px}h2{font-size:18px;margin:0 0 6px}
.lead{color:var(--muted)}ol,ul{padding-left:22px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:16px 0}
.imgs{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0}.imgs figure{margin:0}.imgs figcaption{font-size:12px;color:var(--muted);text-align:center}
.imgs img{width:100%;height:auto;display:block;background:#2b2f36;border-radius:6px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;font-size:14px;vertical-align:top}th{color:var(--muted);font-weight:600}
.tag{font-size:12px;border-radius:6px;padding:1px 7px;white-space:nowrap}.tag.pend{background:var(--pend-bg);color:var(--pend)}.tag.ok{background:var(--ok-bg);color:var(--ok)}
.meta{font-size:13px;color:var(--muted)}code{font-size:13px}.tablewrap{overflow-x:auto}
.single img{max-width:100%;height:auto;display:block;border-radius:6px}
@media (max-width:640px){.imgs{grid-template-columns:1fr}}
"""


NOTES = {
    "vt1-53-battle-viewer-menu": "「トライ」「シングル」两个按钮暂保留日文（游戏里的出处未确认）。",
    "aid-banner-5": "壁纸一览在挑战模式全部通关后才开放，预览镜像里未能实机查看。",
    "vt1-28-logo": "“特别篇”是 Special Disc 的译名建议，待确认；主 logo 不动。",
}


def page(embed: bool) -> str:
    def src(rel: str) -> str:
        if not embed:
            return rel
        return "data:image/png;base64," + base64.b64encode((OUT / rel).read_bytes()).decode()

    def texts_table(j):
        rows = ["<div class=\"tablewrap\"><table><tr><th>日文</th><th>中文</th><th>状态</th></tr>"]
        for t in j["texts"]:
            cls = "pend" if t["status"] == "待定" else "ok"
            rows.append(f"<tr><td>{html.escape(t['ja'])}</td><td>{html.escape(t['zh'])}</td><td><span class=\"tag {cls}\">{html.escape(t['status'])}</span></td></tr>")
        rows.append("</table></div>")
        return "".join(rows)

    finished, pending = [], []
    for j in jobs:
        folder = f"jobs/{j['slug']}"
        if j["method"] in ("source_rebuild", "main_recipe"):
            finished_previews(j["slug"])
        if (OUT / folder / "preview-zh.png").exists() or (OUT / folder / "trial-zh-centred-palette.png").exists():
            finished.append(j)
        else:
            pending.append(j)
    out = ["<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
           "<title>SP Disc 去字与中文图</title><style>", CSS, "</style></head><body><main>",
           "<h1>Special Disc：带背景图片的中文图</h1>",
           f"<p class=\"lead\">2026-09-18。{len(finished)} 项已做好中文，{len(pending)} 项待处理（标题副标题条为 9-18 追加）。做好的图已写入预览镜像 "
           "（该历史预览现已归档为差分基线），并在 LRPS2 里逐屏核对；历史写入记录见 "
           "<code>work/build/special-disc/preview/manifest.json</code>。唯一日常镜像为 "
           "<code>build/iso/special-disc/sp-current.iso</code>。每项左为日文原图，右为目前的中文图。</p>"]
    out.append(f"<h2 style=\"margin-top:28px\">已做好中文（{len(finished)} 项）</h2>")
    for j in finished:
        folder = f"jobs/{j['slug']}"
        out.append(f"<div class=\"card\"><h2>{html.escape(j['title'])} <span class=\"tag ok\">已完成</span></h2>")
        if (OUT / folder / "preview-zh.png").exists():
            out.append("<div class=\"imgs\">")
            out.append(f"<figure><img src=\"{src(folder + '/preview-ja.png')}\" alt=\"日文原图\"><figcaption>日文原图</figcaption></figure>")
            out.append(f"<figure><img src=\"{src(folder + '/preview-zh.png')}\" alt=\"目前的中文图\"><figcaption>目前的中文图</figcaption></figure>")
            out.append("</div>")
        else:
            out.append(f"<div class=\"single\"><img src=\"{src(folder + '/trial-zh-centred-palette.png')}\" alt=\"日文原图与中文图\"></div>"
                       "<p class=\"meta\">左为日文原图，右为目前的中文图</p>")
        out.append(texts_table(j))
        out.append(f"<p class=\"meta\">做法：{html.escape(HOW.get(j['method'], ''))}</p>")
        if j["slug"] in NOTES:
            out.append(f"<p class=\"meta\">备注：{html.escape(NOTES[j['slug']])}</p>")
        out.append("</div>")
    if pending:
        out.append(f"<h2 style=\"margin-top:28px\">待处理（{len(pending)} 项）</h2>")
        for j in pending:
            folder = f"jobs/{j['slug']}"
            out.append(f"<div class=\"card\"><h2>{html.escape(j['title'])} <span class=\"tag pend\">待处理</span></h2>")
            out.append(f"<div class=\"single\"><img src=\"{src(folder + '/source.png')}\" alt=\"日文原图\"></div>")
            out.append(texts_table(j))
            out.append("</div>")
    out.append("</main></body></html>")
    return "".join(out)


(OUT / "index.html").write_text(page(False), encoding="utf-8")
(OUT / "kit-embedded.html").write_text(page(True), encoding="utf-8")
print(len(jobs), "jobs")
for j in jobs:
    print(j["slug"], j["mask_boxes"][:2], "...")
