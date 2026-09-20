"""Feature search for text-free sources of the five Special Theatre banners.

The first pass (find_banner_sources.py) used multi-scale template matching on
AIDDATA and changed SP pictures only and found nothing above 0.69. This pass:

  * uses SIFT keypoints outside each banner's text box, with horizontally
    flipped and luminance-inverted template variants, and RANSAC affine
    verification (inlier count is the score);
  * searches every large SP TIM2 picture (matched and unmatched), all AIDDATA
    pictures and every frame of the three SP movies (MPG/*.PSS, 640x480).

Read-only. Results: banner-sources-sift.json and sift-hits/ previews.
"""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
sys.path.insert(0, str(ROOT / "tools"))
from srwz.psmt4 import _validated_layout  # noqa: E402
from srwz.tim2 import parse_tim2  # noqa: E402
from srwz.tim2_writeback import _csm1_palette_offset, _psmt8_stored_offset  # noqa: E402

ISO = ROOT / "rom/Super Robot Taisen Z - Special Disc [J].iso"
TD = ROOT / "work/analysis/sp-texture-diff-20260912"
AID = ROOT / "work/analysis/sp-aiddata-images-20260912/images"
HITS = OUT / "sift-hits"
BANNER_ART = (0, 0, 620, 78)  # art area inside the 1024x128 texture
# Title text and underline, excluded from keypoint detection (x0, y0, x1, y1).
TEXT_BOXES = {1: (228, 24, 620, 78), 2: (336, 24, 620, 78), 3: (314, 24, 620, 78),
              4: (318, 18, 620, 78), 5: (352, 24, 620, 78)}
MOVIES = (("MPG/MIDPRG.PSS", 475585, 71270404), ("MPG/OPPRG.PSS", 510386, 366247940),
          ("MPG/EDPRG.PSS", 300000, 359596036))
STILL_MEMBERS = {"DATA/VT1.BIN", "DATA/MTV_BGC.BIN", "DATA/JTIM.BIN", "DATA/NISVDATA.BIN",
                 "KURODATA/KVMDATA.BIN", "DATA/MTV_ITEM.BIN", "DATA/MTZSPROP.BIN", "DATA/HSFC.BIN",
                 "BTL/TBG.BIN", "BTL/TCI.BIN", "BTL/OP.BIN", "BTL/TBA.BIN"}
MIN_INLIERS = 10


def banner_grey(k: int) -> tuple[np.ndarray, np.ndarray]:
    im = cv2.imread(str(OUT / "jobs" / f"aid-banner-{k}" / "source.png"), cv2.IMREAD_UNCHANGED)
    x0, y0, x1, y1 = BANNER_ART
    im = im[y0:y1, x0:x1]
    alpha = im[..., 3].astype(np.float32) / 255.0
    grey = cv2.cvtColor(im[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32) * alpha
    mask = (im[..., 3] > 0).astype(np.uint8) * 255
    tx0, ty0, tx1, ty1 = TEXT_BOXES[k]
    mask[ty0:ty1, tx0:tx1] = 0
    mask[:, 600:] = 0  # bevelled right end
    return grey.astype(np.uint8), mask


def template_features():
    sift = cv2.SIFT_create(nfeatures=1500)
    out = []
    for k in TEXT_BOXES:
        grey, mask = banner_grey(k)
        up = cv2.resize(grey, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        upm = cv2.resize(mask, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        for flip in (False, True):
            for invert in (False, True):
                g, m = up, upm
                if flip:
                    g, m = g[:, ::-1].copy(), m[:, ::-1].copy()
                if invert:
                    g = 255 - g
                kp, des = sift.detectAndCompute(g, m)
                pts = np.float32([p.pt for p in kp]) / 2.0  # back to banner pixels
                if flip:
                    pts[:, 0] = (BANNER_ART[2] - BANNER_ART[0]) - 1 - pts[:, 0]
                out.append((k, flip, invert, pts, des))
    return out


TPL = None
SIFT = None
MATCHER = None


def _init():
    global TPL, SIFT, MATCHER
    TPL = template_features()
    SIFT = cv2.SIFT_create(nfeatures=4000)
    MATCHER = cv2.BFMatcher(cv2.NORM_L2)


def match_grey(img: np.ndarray):
    """Return [(banner, flip, invert, inliers, affine banner->image)] for one image."""
    if TPL is None:
        _init()
    scale = 1.0
    if max(img.shape) < 640:  # small pictures: upsample so keypoints survive
        scale = 640 / max(img.shape)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    kp, des = SIFT.detectAndCompute(img, None)
    if des is None or len(kp) < 8:
        return []
    ipts = np.float32([p.pt for p in kp]) / scale
    rows = []
    for k, flip, invert, tpts, tdes in TPL:
        if tdes is None or len(tdes) < 8:
            continue
        pairs = MATCHER.knnMatch(tdes, des, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.8 * n.distance]
        if len(good) < MIN_INLIERS:
            continue
        src = tpts[[m.queryIdx for m in good]]
        dst = ipts[[m.trainIdx for m in good]]
        A, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                                      maxIters=4000, confidence=0.995)
        if A is None:
            continue
        n = int(inl.sum())
        sx, sy = np.hypot(A[0, 0], A[1, 0]), np.hypot(A[0, 1], A[1, 1])
        if n >= MIN_INLIERS and 0.15 < sx < 8 and 0.15 < sy < 8 and 0.5 < sx / sy < 2:
            rows.append((k, flip, invert, n, A.tolist()))
    return rows


# ---------------------------------------------------------------- stills

@lru_cache(maxsize=None)
def psmt8_perm(w: int, h: int) -> np.ndarray:
    ys, xs = np.mgrid[0:h, 0:w]
    return np.array([_psmt8_stored_offset(int(x), int(y), w) for x, y in zip(xs.ravel(), ys.ravel())])


@lru_cache(maxsize=None)
def psmt4_perm(w: int, h: int, row_major: bool) -> np.ndarray:
    return np.array(_validated_layout(w, h, row_major)[0])


def roughness(rgb: np.ndarray) -> float:
    f = rgb.astype(np.int32)
    return float(np.abs(np.diff(f, axis=0)).mean() + np.abs(np.diff(f, axis=1)).mean())


def render_still(job) -> tuple[str, np.ndarray]:
    ident, rec_name, pic = job
    rgb = render_rgb(rec_name, pic)
    return ident, cv2.cvtColor(np.ascontiguousarray(rgb[..., ::-1]), cv2.COLOR_BGR2GRAY)


def render_rgb(rec_name: str, pic: int) -> np.ndarray:
    """Palette-0 RGB preview; the smoother of the candidate pixel layouts wins."""
    rec = (TD / "tim2" / rec_name).read_bytes()
    t = parse_tim2(rec)
    q = t.pictures[pic]
    w, h = q.width, q.height
    a = q.offset + q.header_size
    raw = np.frombuffer(rec[a:a + q.image_size], np.uint8)
    pal = rec[a + q.image_size:a + q.image_size + q.clut_size]
    if not pal and q.uses_shared_clut:
        for prev in t.pictures[:pic]:
            if prev.clut_size:
                b = prev.offset + prev.header_size + prev.image_size
                pal = rec[b:b + prev.clut_size]
    if q.image_type in (1, 2, 3):
        if q.image_type == 3:
            rgb = raw.reshape(h, w, 4)[..., :3]
        elif q.image_type == 2:
            rgb = raw.reshape(h, w, 3)
        else:
            v = raw.view("<u2").reshape(h, w).astype(np.int32)
            rgb = np.stack([((v >> s) & 31) * 255 // 31 for s in (0, 5, 10)], -1).astype(np.uint8)
        variants = [rgb]
    else:
        depth = q.clut_type & 15
        unit = {1: 2, 2: 3, 3: 4}[depth]
        ncol = 16 if q.image_type == 4 else 256
        colours = np.zeros((256, 3), np.uint8)
        for n in range(ncol):
            pn = n if q.clut_type & 128 or len(pal) // unit < 32 else _csm1_palette_offset(n)
            c = pal[pn * unit:(pn + 1) * unit]
            if len(c) < unit:
                continue
            if depth == 1:
                v = int.from_bytes(c, "little")
                colours[n] = [((v >> s) & 31) * 255 // 31 for s in (0, 5, 10)]
            else:
                colours[n] = list(c[:3])
        if q.image_type == 4:
            nib = np.stack([raw & 15, raw >> 4], 1).ravel()
            idxs = [nib[: w * h]]
            for rm in (True, False):
                try:
                    idxs.append(nib[psmt4_perm(w, h, rm)])
                except Exception:
                    pass
        else:
            idxs = [raw]
            if (w, h) != (640, 448):
                try:
                    idxs.append(raw[psmt8_perm(w, h)])
                except Exception:
                    pass
        variants = [colours[i.reshape(h, w)] for i in idxs]
    return min(variants, key=roughness)


def still_worker(job):
    try:
        ident, grey = render_still(job)
    except Exception as e:  # noqa: BLE001
        return job[0], None, str(e)
    return ident, match_grey(grey), None


def aid_worker(path_str):
    img = cv2.imread(path_str, cv2.IMREAD_GRAYSCALE)
    return path_str, match_grey(img), None


def still_jobs():
    inv = json.loads((TD / "sp-inventory.json").read_text())
    seen, jobs = set(), []
    for r in inv:
        if r["member"] not in STILL_MEMBERS:
            continue
        for p in r["pictures"]:
            if p["width"] * p["height"] < 256 * 128 or p["identity"] in seen:
                continue
            seen.add(p["identity"])
            jobs.append((f'{p["member"]}:{p["id"]}', p["record_sha256"] + ".tm2", p["picture"]))
    return jobs


# ---------------------------------------------------------------- movies

def movie_frames(name: str, lba: int, size: int):
    start = lba * 2048
    url = f"subfile,,start,{start},end,{start + size},,:{ISO}"
    cmd = ["ffmpeg", "-v", "error", "-i", url, "-map", "0:v:0", "-vf", "yadif=mode=0:parity=auto:deint=1",
           "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n = 0
    while True:
        buf = proc.stdout.read(640 * 480)
        if len(buf) < 640 * 480:
            break
        yield n, np.frombuffer(buf, np.uint8).reshape(480, 640)
        n += 1
    proc.wait()


def frame_worker(item):
    tag, n, frame = item
    return f"{tag}#{n}", match_grey(frame), None


def main() -> None:
    HITS.mkdir(exist_ok=True)
    hits = []
    with ProcessPoolExecutor(max_workers=15, initializer=_init) as pool:
        jobs = still_jobs()
        print("still pictures", len(jobs), flush=True)
        for ident, rows, err in pool.map(still_worker, jobs, chunksize=8):
            for r in rows or []:
                hits.append(dict(source=ident, banner=r[0], flip=r[1], invert=r[2], inliers=r[3], affine=r[4]))
        aid = sorted(str(p) for p in AID.glob("block-*.png"))
        print("aiddata pictures", len(aid), flush=True)
        for ident, rows, err in pool.map(aid_worker, aid, chunksize=8):
            for r in rows or []:
                hits.append(dict(source=Path(ident).name, banner=r[0], flip=r[1], invert=r[2], inliers=r[3], affine=r[4]))
        print("stills done, hits", len(hits), flush=True)
        for name, lba, size in MOVIES:
            items = ((name, n, f) for n, f in movie_frames(name, lba, size))
            count = 0
            for ident, rows, err in pool.map(frame_worker, items, chunksize=16):
                count += 1
                for r in rows or []:
                    hits.append(dict(source=ident, banner=r[0], flip=r[1], invert=r[2], inliers=r[3], affine=r[4]))
                if count % 1000 == 0:
                    print(name, "frames", count, "hits", len(hits), flush=True)
            print(name, "frames", count, flush=True)
    report = {}
    for k in TEXT_BOXES:
        rows = sorted((h for h in hits if h["banner"] == k), key=lambda h: -h["inliers"])
        report[k] = rows[:40]
        print(f"banner {k}: {len(rows)} hits")
        for h in rows[:8]:
            print(f'   {h["inliers"]:4d} flip={h["flip"]!s:5} inv={h["invert"]!s:5} {h["source"]}')
    (OUT / "banner-sources-sift.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
