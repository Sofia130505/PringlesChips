#!/usr/bin/env python3
"""Prepare M3Kang for the Arduino UNO Q, on your laptop.

M3Kang stores each problem as text plus an image. The text has the question
but not the five answer options: those only appear in the image. This script:

1. downloads the parquet shards you ask for from Hugging Face,
2. keeps the languages you ask for,
3. reads the options A to E from each image with OCR (RapidOCR, offline),
4. splits the problems into train and validation by problem ID, so a
   problem and its translations never land on both sides,
5. writes small JSONL files (no images) that you copy to the board.

Usage:
    python3 laptop/prepare_m3kang.py                      # English and Catalan
    python3 laptop/prepare_m3kang.py --languages eng,cat,esp
    python3 laptop/prepare_m3kang.py --val-years 2024     # hold out a whole year
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import Counter

DATASET = "qualcomm/M3Kang"
SHARD = "data/{split}-{index:05d}-of-{total:05d}.parquet"
SHARDS = {"high_quality": 4, "standard": 10}
LETTERS = "ABCDE"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--split", default="high_quality", choices=sorted(SHARDS))
    p.add_argument("--shards", default="0",
                   help="comma-separated shard numbers, or 'all'. Shard 0 of high_quality has "
                        "eng, cat, fra, esp, ind, deu, swh, vie, tur, zho, kor, arb, jpn, lit")
    p.add_argument("--parquet", nargs="*", help="use local parquet files instead of downloading")
    p.add_argument("--languages", default="eng,cat", help="M3Kang language codes, e.g. eng,cat,esp")
    p.add_argument("--val-fraction", type=float, default=0.15, help="share of problem IDs held out")
    p.add_argument("--val-years", default="", help="hold out these years instead, e.g. 2023,2024")
    p.add_argument("--out", default="data", help="output folder")
    p.add_argument("--no-ocr", action="store_true", help="skip OCR; options will be empty")
    p.add_argument("--save-images", action="store_true", help="also save problem images as PNG")
    p.add_argument("--limit", type=int, default=0, help="only process the first N rows (for testing)")
    return p.parse_args()


def shard_paths(args):
    if args.parquet:
        return args.parquet
    from huggingface_hub import hf_hub_download
    total = SHARDS[args.split]
    indexes = range(total) if args.shards == "all" else [int(s) for s in args.shards.split(",")]
    paths = []
    for i in indexes:
        name = SHARD.format(split=args.split, index=i, total=total)
        print(f"Downloading {name} (cached after the first time)...", flush=True)
        paths.append(hf_hub_download(DATASET, name, repo_type="dataset"))
    return paths


# --- Reading the options from the image -------------------------------------
#
# OCR returns text boxes. The options are the last A..E sequence in reading
# order, usually on one row at the bottom. OCR noise we handle, seen on real
# M3Kang images: "A)21" (no space), "E16" (lost parenthesis), "C" and "13" in
# separate boxes, and ")768351" (parenthesis attached to the value).

# Kangaroo papers print the options as "(A) 12", so a leading "(" is allowed too.
MARKER = re.compile(r"^\s*[\(（]?\s*([A-E])\s*([\)）\]:.]?)\s*(.*)$")

# RapidOCR's default model reads Chinese and English, so on Latin-script images it
# sometimes returns CJK look-alikes: a minus sign or dash comes back as "一" (U+4E00,
# Chinese "one"), and brackets, colons and digits as their full-width forms.
# Full-width ASCII (U+FF01-FF5E) is folded to plain ASCII; this table maps the rest.
# (Not NFKC: it would also turn "cm²" into "cm2" and "½" into "1⁄2".)
CJK_LOOKALIKES = str.maketrans({
    "一": "-", "ー": "-", "－": "-", "—": "-", "–": "-", "‒": "-", "‐": "-", "−": "-",
    "。": ".", "、": ",", "，": ",", "：": ":", "；": ";",
    "（": "(", "）": ")", "【": "[", "】": "]", "「": '"', "」": '"',
    "〇": "0", "口": "□",
})


def clean_ocr_text(text):
    """Normalize one OCR string: full-width forms to ASCII, CJK look-alikes to what they stand for."""
    text = text.translate(CJK_LOOKALIKES)
    return "".join(chr(ord(c) - 0xFEE0) if "！" <= c <= "～" else c for c in text).replace("　", " ")


def reading_order(boxes):
    """Sort OCR boxes into rows (top to bottom), then left to right."""
    items = []
    for box, text, _score in boxes:
        text = clean_ocr_text(text)
        ys = [pt[1] for pt in box]
        xs = [pt[0] for pt in box]
        items.append({"x": min(xs), "y": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys), "text": text})
    items.sort(key=lambda it: it["y"])
    rows, current = [], []
    for it in items:
        if current and abs(it["y"] - current[-1]["y"]) > 0.6 * max(it["h"], current[-1]["h"]):
            rows.append(current)
            current = []
        current.append(it)
    if current:
        rows.append(current)
    return [it for row in rows for it in sorted(row, key=lambda it: it["x"])]


def is_marker(text, letter, strict):
    m = MARKER.match(text)
    if not m or m.group(1) != letter:
        return None
    paren, rest = m.group(2), m.group(3)
    if paren:
        return rest
    if strict:
        return None
    # Without a parenthesis, only accept "C" alone or "E16"-style values,
    # so words such as "ADA" or figure labels with text are not markers.
    if rest == "" or re.match(r"^[-+−\d]", rest):
        return rest
    return None


def parse_options(boxes):
    """Return {"A": "12", ..., "E": "24"}, or {} when the options are not text."""
    items = reading_order(boxes)
    starts = [i for i, it in enumerate(items) if is_marker(it["text"], "A", strict=True) is not None]
    for start in reversed(starts):  # the options are the last A..E sequence
        options, current, i = {}, None, start
        expected = iter(LETTERS)
        letter = next(expected)
        while i < len(items):
            text = items[i]["text"]
            rest = is_marker(text, letter, strict=(letter == "A")) if letter else None
            if rest is not None:
                current = letter
                options[current] = rest
                letter = next(expected, None)
            elif current:
                options[current] = (options[current] + " " + text).strip()
            i += 1
        if len(options) == 5:
            cleaned = {k: v.lstrip(")）] ").strip() for k, v in options.items()}
            if all(cleaned.values()):
                return cleaned
            return {}  # five markers, but the options are pictures
    return {}



# --- OCR v2a (experiment): second OCR pass on the cropped, upscaled options band --------
def _options_band(image_bytes, boxes, scale=2.5):
    """Crop the options band and upscale it. The band starts just above the lowest box that
    looks like an "A" marker; without one, it is the bottom 35% of the image."""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h = img.shape[0]
    tops = []
    for box, text, _score in boxes or []:
        if MARKER.match(clean_ocr_text(text)) and MARKER.match(clean_ocr_text(text)).group(1) == "A":
            tops.append(min(pt[1] for pt in box))
    top = int(max(tops)) - 40 if tops else int(h * 0.65)
    top = max(0, min(top, h - 20))
    band = img[top:, :]
    return cv2.resize(band, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def ocr_options(ocr, image_bytes):
    """First pass on the whole image; if no options, a second pass on the options band."""
    boxes, _ = ocr(image_bytes)
    boxes = boxes or []
    return boxes, extract_options(image_bytes, boxes, ocr)


def extract_options(image_bytes, boxes, ocr):
    """Options from a first-pass OCR (boxes), with a second pass on the options band if needed."""
    boxes = boxes or []
    options = parse_options(boxes)
    if options:
        return options
    band = _options_band(image_bytes, boxes)
    if band is None:
        return options
    band_boxes, _ = ocr(band)
    band_boxes = _cut_below_markers(band_boxes or [])
    return parse_options(band_boxes)


def _cut_below_markers(boxes):
    """Drop boxes below the lowest option-marker row: figure labels and stray text there
    were being glued onto option E."""
    marker_rows = []
    for box, text, _score in boxes:
        m = MARKER.match(clean_ocr_text(text))
        if m and m.group(1) in "ABCDE" and (m.group(2) or len(clean_ocr_text(text).strip()) <= 3
                                            or re.match(r"^\s*[A-E]\s*[-+\d]", clean_ocr_text(text))):
            ys = [pt[1] for pt in box]
            marker_rows.append((max(ys), max(ys) - min(ys)))
    if not marker_rows:
        return boxes
    bottom, height = max(marker_rows)
    limit = bottom + 0.5 * height
    boxes = [b for b in boxes if (min(pt[1] for pt in b[0]) + max(pt[1] for pt in b[0])) / 2 <= limit]
    # The question's own figure often sits to the right of the options row: keep only boxes
    # within about one option spacing to the right of the right-most marker.
    xs = {}
    for box, text, _score in boxes:
        m = MARKER.match(clean_ocr_text(text))
        if m and m.group(1) in "ABCDE":
            xs.setdefault(m.group(1), min(pt[0] for pt in box))
    if len(xs) >= 3:
        pos = sorted(xs.values())
        spacing = sorted(b - a for a, b in zip(pos, pos[1:]))[len(pos) // 2 - 1]
        right = max(pos) + 1.1 * spacing
        boxes = [b for b in boxes if min(pt[0] for pt in b[0]) <= right]
    return boxes


def make_ocr():
    """RapidOCR on the GPU when onnxruntime-gpu and CUDA are available, else on the CPU.

    GPU: pip install "onnxruntime-gpu[cuda,cudnn]" (instead of onnxruntime) in the venv.
    On an RTX 4060 laptop this was 16x faster than the CPU, with identical OCR text.
    """
    import onnxruntime as ort
    from rapidocr_onnxruntime import RapidOCR
    if "CUDAExecutionProvider" in ort.get_available_providers():
        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()  # the CUDA and cuDNN DLLs from the nvidia-* pip packages
        print("OCR on the GPU (CUDA)", flush=True)
        return RapidOCR(det_use_cuda=True, cls_use_cuda=True, rec_use_cuda=True)
    print("OCR on the CPU (install onnxruntime-gpu for CUDA)", flush=True)
    return RapidOCR()


def main():
    args = parse_args()
    import pyarrow.parquet as pq

    languages = set(args.languages.split(","))
    val_years = set(y for y in args.val_years.split(",") if y)
    os.makedirs(args.out, exist_ok=True)
    if args.save_images:
        os.makedirs(os.path.join(args.out, "images"), exist_ok=True)

    ocr = None
    if not args.no_ocr:
        ocr = make_ocr()

    cache_path = os.path.join(args.out, ".ocr_cache.jsonl")
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                cache[row["key"]] = row["options"]
    cache_file = open(cache_path, "a", encoding="utf-8")

    rows = []
    t0 = time.time()
    for path in shard_paths(args):
        table = pq.read_table(path, columns=["language"])
        wanted = [i for i, lang in enumerate(table.column(0).to_pylist()) if lang in languages]
        if not wanted:
            continue
        full = pq.read_table(path).take(wanted)
        for i in range(full.num_rows):
            if args.limit and len(rows) >= args.limit:
                break
            r = {c: full.column(c)[i].as_py() for c in ("id", "language", "level", "text_only", "label", "text")}
            key = f"{r['id']}|{r['language']}"
            image = full.column("image")[i].as_py()["bytes"]
            if args.save_images:
                with open(os.path.join(args.out, "images", key.replace("|", "_") + ".png"), "wb") as f:
                    f.write(image)
            if key in cache:
                options = cache[key]
            elif ocr:
                boxes, options = ocr_options(ocr, image)
                cache[key] = options
                # The cleaned OCR lines in reading order are cached too, so that
                # orchestration/dump_ocr_raw.py can reuse them instead of running OCR again.
                lines = [it["text"] for it in reading_order(boxes or [])]
                cache_file.write(json.dumps({"key": key, "options": options, "lines": lines},
                                            ensure_ascii=False) + "\n")
                cache_file.flush()
            else:
                options = {}
            year = r["id"].split("_")[1]
            if val_years:
                split = "val" if year in val_years else "train"
            else:
                bucket = int(hashlib.sha256(r["id"].encode()).hexdigest(), 16) % 1000
                split = "val" if bucket < args.val_fraction * 1000 else "train"
            rows.append({
                "id": r["id"], "language": r["language"], "level": r["level"], "year": int(year),
                "text_only": r["text_only"], "text": r["text"].strip(), "options": options,
                "label": r["label"], "split": split,
            })
            if len(rows) % 100 == 0:
                rate = len(rows) / (time.time() - t0)
                print(f"  {len(rows)} rows, {rate:.1f} rows/s", flush=True)
    cache_file.close()

    for split in ("train", "val"):
        out = os.path.join(args.out, f"{split}.jsonl")
        with open(out, "w", encoding="utf-8") as f:
            for r in rows:
                if r["split"] == split:
                    f.write(json.dumps({k: v for k, v in r.items() if k != "split"}, ensure_ascii=False) + "\n")

    report(rows, args.out)


def report(rows, out):
    if not rows:
        sys.exit("No rows matched. Check --languages and --shards.")
    by = Counter((r["split"], r["language"]) for r in rows)
    with_options = sum(1 for r in rows if r["options"])
    text_only = [r for r in rows if r["text_only"]]
    labels = Counter(r["label"] for r in rows if r["split"] == "train")
    top, count = labels.most_common(1)[0]
    print()
    print(f"Wrote {out}/train.jsonl and {out}/val.jsonl")
    for (split, lang), n in sorted(by.items()):
        print(f"  {split:5} {lang}: {n}")
    print(f"Options read from the image: {with_options}/{len(rows)} ({100 * with_options / len(rows):.0f}%)")
    if text_only:
        ok = sum(1 for r in text_only if r["options"])
        print(f"  of which text-only problems: {ok}/{len(text_only)} ({100 * ok / len(text_only):.0f}%)")
    print(f"Most common answer in train: {top} ({100 * count / sum(labels.values()):.1f}%). "
          f"Always answering {top} is the floor to beat.")


if __name__ == "__main__":
    main()


# ---- round 1 (OCR improver): geometric option assignment ----
import re


def _ocr_items(boxes):
    """RapidOCR items -> geometry dicts (left/right edge, row id), in reading order."""
    items = []
    for box, text, _score in boxes:
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        h = max(ys) - min(ys)
        items.append({
            "x0": min(xs),
            "x1": max(xs),
            "y": (min(ys) + max(ys)) / 2.0,
            "h": h if h > 1.0 else 1.0,
            "text": clean_ocr_text(text),
        })
    items.sort(key=lambda it: it["y"])
    rows, current = [], []
    for it in items:
        if current and abs(it["y"] - current[-1]["y"]) > 0.6 * max(it["h"], current[-1]["h"]):
            rows.append(current)
            current = []
        current.append(it)
    if current:
        rows.append(current)
    ordered = []
    for r, row in enumerate(rows):
        for it in sorted(row, key=lambda it: it["x0"]):
            it["row"] = r
            ordered.append(it)
    return ordered


def _clean_rest(rest):
    """Remove OCR junk glued in front of the value inside the marker box."""
    rest = rest.strip().lstrip(")）]】| ").strip()
    return re.sub(r"^[a-z](?=\d)", "", rest).strip()  # "g9°" -> "9°"


def _join_value(rest, pieces):
    """Build the option value, dropping a one-char fragment the next box repeats."""
    if pieces:
        head = pieces[0][:1]
        if len(rest) == 1:
            if rest.isdigit() and head == rest:
                rest = ""          # "B)4" + "40"  -> "40"
            elif rest.isalpha() and head.isdigit():
                rest = ""          # "D)J" + "15"  -> "15"
    parts = [rest] if rest else []
    parts.extend(p for p in pieces if p)
    return " ".join(parts).strip()


def _assign_markers(items, markers):
    """Give each A..E marker only the boxes that geometrically continue its value."""
    values, used, spans = {}, set(), {}

    # pass 1: same row, chained to the right of the marker
    for k, (idx, letter, rest) in enumerate(markers):
        m = items[idx]
        vx0, vx1 = m["x0"], m["x1"]
        end = markers[k + 1][0] if k + 1 < len(markers) else len(items)
        pieces = []
        for j in range(idx + 1, end):
            it = items[j]
            if j in used or it["row"] != m["row"]:
                continue
            if it["x0"] < vx0 - 0.8 * m["h"]:
                continue
            if it["x0"] > vx1 + 1.6 * m["h"]:
                continue  # too far right: figure label / page furniture
            used.add(j)
            pieces.append(it["text"])
            vx1 = max(vx1, it["x1"])
        values[letter] = _join_value(_clean_rest(rest), pieces)
        spans[letter] = (m, vx0, vx1, end)

    # pass 2: a value that wrapped directly below, only if its row starts no option
    for k, (idx, letter, _rest) in enumerate(markers):
        m, vx0, vx1, end = spans[letter]
        if any(items[markers[j][0]]["row"] == m["row"] for j in range(k + 1, len(markers))):
            continue  # another option still starts on this row
        for j in range(idx + 1, end):
            it = items[j]
            if j in used or it["row"] == m["row"]:
                continue
            if any(items[mi]["row"] == it["row"] for mi, _l, _v in markers):
                continue
            dy = it["y"] - m["y"]
            if dy <= 0 or dy > 2.0 * max(m["h"], it["h"]):
                continue
            if it["x0"] > vx1 + 1.0 * m["h"] or it["x1"] < vx0 - 0.5 * m["h"]:
                continue
            used.add(j)
            values[letter] = (values[letter] + " " + it["text"]).strip()
            vx1 = max(vx1, it["x1"])
    return values


def parse_options(boxes):
    """Return {"A": "12", ..., "E": "24"}, or {} when the options are not text."""
    items = _ocr_items(boxes)
    n = len(items)
    starts = [i for i, it in enumerate(items) if is_marker(it["text"], "A", strict=True) is not None]
    for start in reversed(starts):  # the options are the last A..E sequence
        markers, letter = [], None
        expected = iter(LETTERS)
        letter = next(expected, None)
        for i in range(start, n):
            if letter is None:
                break
            rest = is_marker(items[i]["text"], letter, strict=(letter == "A"))
            if rest is not None:
                markers.append((i, letter, rest))
                letter = next(expected, None)
        if len(markers) != len(LETTERS):
            continue
        values = _assign_markers(items, markers)
        cleaned = {k: v.lstrip(")）] ").strip() for k, v in values.items()}
        if all(cleaned.values()):
            return cleaned
        return {}  # five markers, but the options are pictures
    return {}


# ---- round 2b (OCR improver): unit/currency/symbol normalisation ----
_parse_options_before_r2 = parse_options

# --------------------------------------------------------------- round 2 ----
# Deterministic repair of units / currency / symbols in the five raw option
# strings.  Standard library only; uses nothing but the option strings.
import re

_SUP = {"2": "²", "3": "³"}

# a length/area/volume unit, optional exponent written as 2/3/²/³/^2/^3
_UNIT_RE = re.compile(
    r"(?<![A-Za-zÀ-ÿ])(km|dm|cm|mm|m)\s*(\^?\s*[²³23])?(?![A-Za-zÀ-ÿ0-9²³])")

# "cm²2" / "cm³3"  ->  drop the duplicated exponent digit
_DUP_SUP = re.compile(r"([²³])\s*([23])(?![0-9])")

# a bare numeric option, e.g. "30", "14,5", "1 250"
_PLAIN_NUM = re.compile(r"[0-9][0-9., ]*")

# a plain integer option, e.g. "45" (used by the exponent-pattern rule)
_PLAIN_INT = re.compile(r"[0-9]{1,5}")


def _dup_sup(m):
    return m.group(1) if _SUP.get(m.group(2)) == m.group(1) else m.group(0)


def _clean_one(text):
    """Per-option, context-free symbol repair."""
    s = "" if text is None else str(text).strip()
    if not s:
        return s
    s = s.replace("∈", "€")                     # OCR reads € as ∈
    s = _DUP_SUP.sub(_dup_sup, s)               # cm²2 -> cm²
    s = re.sub(r"(?<=[0-9])\s*€", " €", s)      # 40∈ -> 40 €
    if "°" in s:                                # 17°30′ -> 17° 30'
        s = s.replace("′", "'").replace("’", "'").replace("″", '"')
        s = re.sub(r"°\s*(?=[0-9])", "° ", s)
    return s


def _norm_exp(raw):
    if not raw:
        return None
    d = raw.strip().lstrip("^").strip()
    return _SUP.get(d, d)


def _unit_of(s):
    """(base, exponent, span) for the single unit in s, else None."""
    hits = list(_UNIT_RE.finditer(s))
    if len(hits) != 1:          # none, or ambiguous (two different units)
        return None
    m = hits[0]
    return m.group(1).lower(), _norm_exp(m.group(2)), m.span()


def _with_unit(prefix, unit, suffix):
    if prefix and prefix[-1].isdigit():
        prefix += " "
    return prefix + unit + suffix


def _fix_currency(values):
    """If >=3 options carry €, the bare numbers among them carry it too."""
    if sum(1 for v in values if "€" in v) < 3:
        return values
    out = []
    for v in values:
        if "€" in v:
            out.append(v)
        elif _PLAIN_NUM.fullmatch(v or ""):
            out.append(_with_unit(v.rstrip(), "€", ""))
        else:
            out.append(v)
    return out


def _fix_units(values):
    """Majority vote on (unit, exponent) across the five options."""
    infos = [_unit_of(v) for v in values]
    counts = {}
    for info in infos:
        if info is None:
            continue
        key = (info[0], info[1])
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return values
    best, votes = max(counts.items(), key=lambda kv: kv[1])
    if votes < 3:
        return values

    out = []
    for v, info in zip(values, infos):
        if info is None:
            if votes >= 4 and _PLAIN_NUM.fullmatch(v or ""):
                out.append(_with_unit(v.rstrip(), best[0] + (best[1] or ""), ""))
            else:
                out.append(v)
            continue
        base, exp, (start, end) = info
        if base == best[0]:
            # keep a bare length unit bare unless the vote is overwhelming
            if exp is None and best[1] is not None and votes < 4:
                unit = base
            else:
                unit = best[0] + (best[1] or "")
        else:
            unit = base + (exp or "")
        out.append(_with_unit(v[:start].rstrip(), unit, v[end:]))
    return out


def _fix_exponent_pattern(values):
    """{45, 452, 453, 245, 345} -> {45, 45^2, 45^3, 2^45, 3^45}.

    Only fires when a single base explains all five options in *both*
    directions (base+digit and digit+base); a plain run like
    {12, 123, 124, 125, 126} is left untouched.
    """
    if len(values) != 5 or not all(_PLAIN_INT.fullmatch(v or "") for v in values):
        return values
    for base in sorted(set(values), key=len):
        up = down = 0
        ok = True
        for v in values:
            if v == base:
                continue
            if len(v) == len(base) + 1 and v.startswith(base):
                up += 1
            elif len(v) == len(base) + 1 and v.endswith(base):
                down += 1
            else:
                ok = False
                break
        need = 2 if len(base) < 2 else 1
        if not ok or up < need or down < need:
            continue
        out = []
        for v in values:
            if v == base:
                out.append(v)
            elif v.startswith(base):
                out.append(base + "^" + v[-1])
            else:
                out.append(v[0] + "^" + base)
        return out
    return values


def normalize_options(options):
    """Correct the five raw option strings; never invent, never use labels."""
    if not isinstance(options, dict) or not options:
        return {} if not isinstance(options, dict) else dict(options)
    keys = list(options.keys())
    values = [_clean_one(options[k]) for k in keys]
    if len(values) == 5:
        values = _fix_currency(values)
        values = _fix_units(values)
        values = _fix_exponent_pattern(values)
    return dict(zip(keys, values))


def parse_options(boxes):
    return normalize_options(_parse_options_before_r2(boxes))


# ---- round r3 (OCR improver) ----
_parse_options_before_r3 = parse_options

import re as _re

_LETTERS = 'ABCDE'
_LABEL_RE = _re.compile(r'^\s*([A-Ea-e])\s*[\)\.\:\-]\s*')
_BAR_CHARS = '-–—−/'
_BAR_ART = '17Ili|'
_TALL_FRAC = 1.45
_TOP_FRAC = 0.15
_BOT_FRAC = 0.10

# A marker letter standing on its own (not glued inside a number/word).
_MARK_RE = _re.compile(r'(?<![0-9A-Za-z])[A-E](?![0-9A-Za-z])')
# A unit that follows a digit: "190cm", "14,5cm2", "50 m", "3kg", "20 €", "30°", "5%".
_r3_UNIT_RE = _re.compile(r'\d\s*(?:cm|mm|km|kg|mg|ml|dm|dB|[mgs]|€|°|%)(?![A-Za-z])', _re.I)


def _good_token(t, rh):
    """True when t can be a numerator/denominator box of a real fraction."""
    s = (t or '').strip()
    if not s or len(s) > 8:
        return False
    if _r3_UNIT_RE.search(s):
        return False
    if len(s) > 1 and _MARK_RE.search(s):
        return False
    for ch in s:
        if ch.isalnum() or ch in 'πΠ√+-−().,':
            continue
        return False
    return True


def _as_items(boxes):
    out = []
    for b in boxes or []:
        if isinstance(b, dict):
            if 'text' in b and 'x' in b and 'y' in b and 'h' in b:
                txt = b['text']
                try:
                    x = float(b['x'])
                    y = float(b['y'])
                    h = float(b['h'])
                except (TypeError, ValueError):
                    continue
                try:
                    w = float(b.get('w', max(h * 0.7, len((txt or '').strip()) * h * 0.55)))
                except (TypeError, ValueError):
                    w = max(h * 0.7, len((txt or '').strip()) * h * 0.55)
                if h <= 0:
                    h = 8.0
                out.append({'x': x, 'y': y, 'w': max(w, 4.0), 'h': h, 't': txt})
            continue

        if not isinstance(b, (list, tuple)) or len(b) < 2:
            continue

        txt = None
        x = y = w = h = None

        if isinstance(b[0], (list, tuple)):
            # Raw RapidOCR box: [[[x1,y1],...], "text", score]
            if isinstance(b[1], str):
                txt = b[1]
            xs = []
            ys = []
            for p in b[0]:
                if not isinstance(p, (list, tuple)) or len(p) < 2:
                    continue
                try:
                    xs.append(float(p[0]))
                    ys.append(float(p[1]))
                except (TypeError, ValueError):
                    pass
            if xs and ys:
                x = min(xs)
                y = min(ys)
                w = max(xs) - x
                h = max(ys) - y

        if txt is not None and x is not None:
            if h is None or h <= 0:
                h = 8.0
            out.append({'x': x, 'y': y, 'w': max(w, 4.0), 'h': h, 't': txt})
            continue

        # Legacy tuple formats: (x, y, h, text), (x, y, w, h, text),
        # (x, y, w, h, score, text)
        if not isinstance(b[-1], str):
            continue
        txt = b[-1]
        try:
            nums = [float(v) for v in b[:-1]]
        except (TypeError, ValueError):
            continue
        if len(nums) == 4:
            x, y, w, h = nums
        elif len(nums) == 3:
            x, y, h = nums
            w = max(h * 0.7, len(txt.strip()) * h * 0.55)
        elif len(nums) == 5:
            x, y, w, h = nums[0], nums[1], nums[2], nums[3]
        else:
            continue
        if h <= 0:
            h = 8.0
        out.append({'x': x, 'y': y, 'w': max(w, 4.0), 'h': h, 't': txt})
    return out


def _label(t):
    m = _LABEL_RE.match(t or '')
    return m.group(1).upper() if m else None


def _bare(t):
    s = (t or '').strip()
    if len(s) == 1 and s in _LETTERS:
        return s
    if len(s) == 2 and s[0] in _LETTERS and not s[1].isalnum():
        return s[0]
    return None


def _median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return 0.0
    if n % 2:
        return v[n // 2]
    return (v[n // 2 - 1] + v[n // 2]) / 2.0


def _centre(b):
    return b['y'] + b['h'] / 2.0


def _markers(items):
    strict = {}
    bare = {}
    for it in items:
        txt = it['t']
        L = _label(txt)
        if L and L not in strict:
            strict[L] = it
        B = _bare(txt)
        if B and B not in bare:
            bare[B] = it

    if len(strict) >= 4:
        chosen = dict(strict)
        cy = _median([_centre(v) for v in chosen.values()])
        rh = max(_median([v['h'] for v in chosen.values()]), 8.0)
        for L in _LETTERS:
            if L in chosen:
                continue
            cand = bare.get(L)
            if cand is not None and abs(_centre(cand) - cy) <= 0.75 * rh:
                chosen[L] = cand
    else:
        chosen = {}
        for L in _LETTERS:
            if L in strict:
                chosen[L] = strict[L]
            elif L in bare:
                chosen[L] = bare[L]
        if len(chosen) < 4:
            return {}, 0.0, 0.0
        cy = _median([_centre(v) for v in chosen.values()])
        rh = max(_median([v['h'] for v in chosen.values()]), 8.0)

    row = {k: v for k, v in chosen.items() if abs(_centre(v) - cy) <= 1.2 * rh}
    if len(row) < 4:
        return {}, 0.0, 0.0

    for L in _LETTERS:
        if L in row:
            continue
        left = [v['x'] for k, v in row.items() if k < L]
        right = [v['x'] for k, v in row.items() if k > L]
        lx = max(left) if left else None
        rx = min(right) if right else None
        guess = ((lx if lx is not None else 0.0) + (rx if rx is not None else 0.0)) / 2.0
        best = None
        for it in items:
            if _bare(it['t']) != L:
                continue
            if abs(_centre(it) - cy) > 0.75 * rh:
                continue
            if lx is not None and it['x'] <= lx:
                continue
            if rx is not None and it['x'] >= rx:
                continue
            if best is None or abs(it['x'] - guess) < abs(best['x'] - guess):
                best = it
        if best is not None:
            row[L] = best

    row = {k: v for k, v in row.items() if abs(_centre(v) - cy) <= 1.2 * rh}
    if len(row) < 4:
        return {}, 0.0, 0.0
    return row, cy, rh


def _clean(s):
    s = (s or '').strip()
    for _ in range(3):
        s2 = s.strip().strip(_BAR_CHARS).strip()
        if s2 == s:
            break
        s = s2
    return s


def _mathfix(s):
    s = (s or '').strip()
    if not s:
        return s
    s = _re.sub(r'[Vv](?=\d)', '√', s)
    s = _re.sub(r'(?<=\d)\.?[cC](?![A-Za-z0-9])', 'x', s)
    if s == 'T':
        s = 'π'
    return s


def _den_clean(box, rh):
    d = _clean(box['t'])
    if len(d) >= 2 and d[0] in _BAR_ART and d[1:].strip():
        if box['h'] >= 0.92 * rh:
            d = d[1:].strip()
    return d


def _paren(s, radical=False):
    core = (s or '').strip()
    if not core:
        return core
    if core[0] == '(' and core[-1] == ')':
        return core
    if any(ch in core for ch in '+-−/'):
        return '(' + core + ')'
    if '√' in core and (radical or len(core) > 3):
        return '(' + core + ')'
    return core


def _split_bar(s):
    core = (s or '').strip()
    for i, ch in enumerate(core):
        if ch not in _BAR_CHARS:
            continue
        if i == 0 or i >= len(core) - 1:
            continue
        a = core[:i].strip()
        b = core[i + 1:].strip()
        if not a or not b:
            continue
        if ch == '-' and not (a.isdigit() and b.isdigit()):
            continue
        if any(c.isalnum() for c in a) and any(c.isalnum() for c in b):
            return a, b
    return None


def _overlap(a, b):
    return min(a['x'] + a['w'], b['x'] + b['w']) > max(a['x'], b['x'])


def _tail(boxes, skip):
    parts = []
    for b in sorted(boxes, key=lambda z: z['x']):
        if any(b is s for s in skip):
            continue
        s = _mathfix((b['t'] or '').strip())
        if s:
            parts.append(s)
    return ' '.join(parts)


def _on_other_row(box, markers, cy, rh):
    """A marker aligned with box, on a row other than the main option row."""
    c = _centre(box)
    if abs(c - cy) <= 0.85 * rh:
        return False
    for m in markers:
        if m is box:
            continue
        if abs(_centre(m) - c) <= 0.8 * rh:
            return True
    return False


def _fraction_text(region, cy, rh, markers):
    boxes = [b for b in region if (b['t'] or '').strip()]
    if not boxes:
        return None

    for b in boxes:
        if b['h'] >= _TALL_FRAC * rh:
            parts = _split_bar(b['t'])
            if parts:
                n = _mathfix(_clean(parts[0]))
                d = _mathfix(_clean(parts[1]))
                if n == 'C':
                    n = 'x'
                if d == 'C' and n.isdigit():
                    d = '3'
                if n and d and _good_token(n, rh) and _good_token(d, rh):
                    out = _paren(n) + '/' + _paren(d, radical=True)
                    tail = _tail([x for x in boxes if x is not b], [])
                    return (out + ' ' + tail).strip() if tail else out

    tops = []
    bots = []
    for b in boxes:
        c = _centre(b)
        if c < cy - _TOP_FRAC * rh:
            tops.append(b)
        elif c > cy + _BOT_FRAC * rh:
            bots.append(b)
    if not tops or not bots:
        return None

    best = None
    for top in tops:
        for bot in bots:
            # Two-row option layout: never pair a value with the row below.
            if _on_other_row(bot, markers, cy, rh):
                continue
            dx = abs(top['x'] - bot['x'])
            if dx > 1.35 * rh and not _overlap(top, bot):
                continue
            if _centre(top) >= _centre(bot):
                continue
            score = dx + 0.25 * abs(_centre(top) - _centre(bot))
            if best is None or score < best[0]:
                best = (score, top, bot)
    if best is None:
        return None

    _, num, den = best
    n = _mathfix(_clean(num['t']))
    d = _mathfix(_den_clean(den, rh))
    if n == 'C':
        n = 'x'
    if d == 'C' and n.isdigit():
        d = '3'
    if not n or not d:
        return None
    if not _good_token(n, rh) or not _good_token(d, rh):
        return None

    out = _paren(n) + '/' + _paren(d, radical=True)
    rest = [b for b in boxes if b is not num and b is not den]
    tail = _tail(rest, [])
    if tail:
        out = out + ' ' + tail
    return out


def _is_frac(v):
    s = (v or '').strip()
    if '/' not in s:
        return False
    a, _, b = s.partition('/')
    return bool(a.strip()) and bool(b.strip())


def _cand_box(region, s):
    want = (s or '').strip()
    if not want:
        return None
    for b in region:
        if _mathfix(_clean(b['t'])) == want:
            return b
    for b in region:
        t = _mathfix(_clean(b['t']))
        if t and want in t:
            return b
    return None


def _neighbours(region, me, rh):
    above = []
    below = []
    mc = _centre(me)
    mx = me['x'] + me['w'] / 2.0
    for b in region:
        if b is me:
            continue
        t = _mathfix(_clean(b['t']))
        if not t or not t.isdigit() or len(t) > 8:
            continue
        bc = _centre(b)
        bx = b['x'] + b['w'] / 2.0
        dx = abs(bx - mx)
        if dx > 1.2 * rh:
            continue
        if bc < mc - 0.15 * rh:
            above.append((mc - bc + dx, t))
        elif bc > mc + 0.15 * rh:
            below.append((bc - mc + dx, t))
    above.sort(key=lambda z: z[0])
    below.sort(key=lambda z: z[0])
    return above, below


def _split_merged(val, region, cy, rh):
    """Recover "num/den" from one merged box (bar read as 1, or lost)."""
    s = (val or '').strip()
    if not s or not s.isdigit() or len(s) > 4:
        return None

    if len(s) == 1:
        me = _cand_box(region, s)
        if me is None:
            return None
        _, below = _neighbours(region, me, rh)
        if below:
            return s + '/' + below[0][1]
        return None

    if len(s) == 2:
        if s[0] != '0' and s[1] != '0' and s[0] != s[1]:
            return s[0] + '/' + s[1]
        return None

    if len(s) == 3 and s[1] == '1' and s[0] != '0' and s[2] != '0':
        # "314" -> 3/4, "312" -> 3/2, "413" -> 4/3
        return s[0] + '/' + s[2]

    me = _cand_box(region, s)
    if me is None:
        return None
    above, _ = _neighbours(region, me, rh)
    for _, t in above:
        if abs(len(t) - len(s)) <= 2:
            return t + '/' + s
    return None


def _extend(merged, ctx):
    vals = {L: merged.get(L, '') for L in _LETTERS}
    n_frac = sum(1 for L in _LETTERS if _is_frac(vals.get(L)))
    if n_frac < 2:
        return merged
    cands = []
    for L in _LETTERS:
        v = (vals.get(L) or '').strip()
        if _is_frac(v):
            continue
        if v.isdigit() and len(v) <= 4:
            cands.append(L)
    if not cands:
        return merged
    for L in cands:
        region = ctx['regions'].get(L) or []
        v = _split_merged(vals.get(L), region, ctx['cy'], ctx['rh'])
        if v:
            merged[L] = v
    return merged


def _rebuild(boxes):
    items = _as_items(boxes)
    if len(items) < 6:
        return None
    mk, cy, rh = _markers(items)
    if len(mk) < 4:
        return None

    markers = []
    for it in items:
        if _label(it['t']) or _bare(it['t']):
            markers.append(it)

    order = sorted(mk.keys(), key=lambda L: mk[L]['x'])
    marker_ids = {id(v) for v in mk.values()}
    regions = {}
    upper_markers = 0
    tall_any = False

    for i, L in enumerate(order):
        lo = mk[L]['x'] - 0.22 * rh
        hi = mk[order[i + 1]]['x'] if i + 1 < len(order) else mk[L]['x'] + 60.0 * rh
        region = []
        for it in items:
            if id(it) in marker_ids:
                if it is mk[L]:
                    rem = _LABEL_RE.sub('', it['t']).strip()
                    if rem:
                        region.append({'x': it['x'] + 0.5 * rh, 'y': it['y'],
                                       'w': max(it['h'], 4.0), 'h': it['h'], 't': rem})
                continue
            if not (lo <= it['x'] < hi):
                continue
            if abs(_centre(it) - cy) > 2.2 * rh:
                continue
            region.append(it)
        regions[L] = region

        if any((b['t'] or '').strip() and _centre(b) < cy - 0.35 * rh for b in region):
            upper_markers += 1
        for b in region:
            if b['h'] >= _TALL_FRAC * rh and _split_bar(b['t']):
                tall_any = True

    if upper_markers < 3 and not tall_any:
        return None

    found = {}
    for L in order:
        v = _fraction_text(regions[L], cy, rh, markers)
        if v:
            found[L] = v
    if not found:
        return None

    ctx = {'regions': regions, 'items': items, 'markers': markers,
           'cy': cy, 'rh': rh}
    return found, ctx


def parse_options(boxes):
    base = _parse_options_before_r3(boxes)
    rebuilt = _rebuild(boxes)
    if not rebuilt:
        return base
    found, ctx = rebuilt

    if isinstance(base, dict):
        merged = dict(base)
    elif isinstance(base, (list, tuple)):
        merged = {L: (base[i] if i < len(base) else '') for i, L in enumerate(_LETTERS)}
    else:
        merged = {}
    for L in _LETTERS:
        merged.setdefault(L, '')
    merged.update(found)

    merged = _extend(merged, ctx)

    for L in _LETTERS:
        if isinstance(merged.get(L), str):
            merged[L] = _mathfix(merged[L])

    def _base_val(L):
        if isinstance(base, dict):
            v = base.get(L, '')
        elif isinstance(base, (list, tuple)):
            i = _LETTERS.index(L)
            v = base[i] if i < len(base) else ''
        else:
            v = ''
        return v if isinstance(v, str) else ''

    # Never return empty strings: fall back to the previous parser per letter.
    for L in _LETTERS:
        cur = merged.get(L, '')
        if not isinstance(cur, str) or not cur.strip():
            bv = _base_val(L)
            if bv.strip():
                merged[L] = bv

    for L in _LETTERS:
        cur = merged.get(L, '')
        if not isinstance(cur, str) or not cur.strip():
            return base

    norm = normalize_options(merged)
    if isinstance(norm, dict):
        for L in _LETTERS:
            v = norm.get(L, '')
            if not isinstance(v, str) or not v.strip():
                return base
        merged = norm

    if isinstance(base, (list, tuple)) and not isinstance(base, dict):
        return [merged.get(L, '') for L in _LETTERS]
    return merged


# ---- round r4 (OCR improver) ----
_parse_options_before_r4 = parse_options
import re


def _r4_has_lone_capital(value, letter):
    if not isinstance(value, str):
        return False
    return re.search(r'(^|[\s(])' + letter + r'(?=[\s)]|$)', value) is not None


def _r4_lone_letter_in_others(values, idx, letter):
    for j, value in enumerate(values):
        if j == idx:
            continue
        if _r4_has_lone_capital(value, letter):
            return True
    return False


def _r4_clean_stray_letters(values, idx):
    value = values[idx]
    if not isinstance(value, str) or not re.search(r'\d', value):
        return value

    m = re.search(r'\s([A-E])$', value)
    if m:
        letter = m.group(1)
        if not _r4_lone_letter_in_others(values, idx, letter):
            value = value[:m.start()]

    def repl(match):
        letter = match.group(1)
        if _r4_lone_letter_in_others(values, idx, letter):
            return match.group(0)
        return ' '

    value = re.sub(r'\s([A-E])\s', repl, value)
    return value


def _r4_clean_glued_unit(value, others):
    if not isinstance(value, str):
        return value
    m = re.match(r'^(.*?)(cm2|cm²|cm3|cm³)([A-Z])$', value)
    if not m:
        return value

    prefix, unit, _junk = m.groups()
    if unit == 'cm2':
        if sum(1 for o in others if isinstance(o, str) and o.strip().endswith('cm²')) >= 2:
            unit = 'cm²'
    elif unit == 'cm3':
        if sum(1 for o in others if isinstance(o, str) and o.strip().endswith('cm³')) >= 2:
            unit = 'cm³'
    return prefix + unit


def _r4_fix_sqrt(value):
    if not isinstance(value, str):
        return value
    return re.sub(
        r'(?<=[a-z0-9(])([Vv])([0-9])',
        lambda m: '√' + m.group(2),
        value
    )


def _r4_fix_decimal_separators(values):
    comma_idxs = []
    dot_idxs = []
    for i, value in enumerate(values):
        if not isinstance(value, str):
            continue
        if re.search(r'\d,\d', value):
            comma_idxs.append(i)
        if re.search(r'\d\.\d', value):
            dot_idxs.append(i)

    if not comma_idxs or not dot_idxs:
        return values

    if len(comma_idxs) > len(dot_idxs):
        preferred = ','
    elif len(dot_idxs) > len(comma_idxs):
        preferred = '.'
    else:
        preferred = ','

    for i, value in enumerate(values):
        if not isinstance(value, str):
            continue
        if preferred == ',':
            values[i] = re.sub(r'(?<=\d)\.(?=\d)', ',', value)
        else:
            values[i] = re.sub(r'(?<=\d),(?=\d)', '.', value)
    return values


def _r4_add_degrees(values):
    degree_count = sum(
        1 for value in values
        if isinstance(value, str) and value.rstrip().endswith('°')
    )
    if degree_count < 3:
        return values

    for i, value in enumerate(values):
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if re.fullmatch(r'\d{2,3}', stripped):
            values[i] = stripped + '°'
    return values


def clean_options(options):
    if not isinstance(options, dict) or not options:
        return {} if not isinstance(options, dict) or not options else options

    keys = list(options.keys())
    original = [options[key] for key in keys]
    values = list(original)

    for i in range(len(values)):
        values[i] = _r4_clean_stray_letters(values, i)

    for i in range(len(values)):
        others = [values[j] for j in range(len(values)) if j != i]
        values[i] = _r4_clean_glued_unit(values[i], others)

    for i in range(len(values)):
        values[i] = _r4_fix_sqrt(values[i])

    values = _r4_fix_decimal_separators(values)
    values = _r4_add_degrees(values)

    for i in range(len(values)):
        if isinstance(values[i], str) and values[i].strip() == '':
            if isinstance(original[i], str) and original[i].strip() != '':
                values[i] = original[i]
            else:
                values[i] = ' '

    return {key: values[i] for i, key in enumerate(keys)}


def parse_options(boxes):
    return clean_options(_parse_options_before_r4(boxes))


# ---- round r5 (OCR improver) ----
_parse_options_before_r5 = parse_options

import re as _r5_re

_R5_ORDER = 'ABCDE'
_R5_MARK = _r5_re.compile(r'(?:^|\s)([A-E])\)')


def _r5_parts(boxes):
    """Flatten boxes into (letter|None, x, y, h, text), splitting inner markers."""
    out = []
    for box in boxes:
        x, y, h = box[0], box[1], box[2]
        text = (box[3] or '').strip()
        if not text:
            continue
        marks = list(_R5_MARK.finditer(text))
        if not marks:
            out.append((None, x, y, h, text))
            continue
        if marks[0].start() > 0:
            head = text[:marks[0].start()].strip()
            if head:
                out.append((None, x, y, h, head))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            out.append((m.group(1), x, y, h, text[m.end():end].strip()))
    return out


def _r5_range(pos, letter):
    """x-bounds of a letter's slot, from the nearest present markers."""
    i = _R5_ORDER.index(letter)
    lo = hi = None
    for j in range(i - 1, -1, -1):
        if _R5_ORDER[j] in pos:
            lo = pos[_R5_ORDER[j]]
            break
    for j in range(i + 1, 5):
        if _R5_ORDER[j] in pos:
            hi = pos[_R5_ORDER[j]]
            break
    return lo, hi


def _r5_take(leftovers, lo, hi):
    """Consume the single unassigned box lying in [lo, hi] on the marker row."""
    cand = [b for b in leftovers
            if (lo is None or b[0] > lo) and (hi is None or b[0] < hi)]
    if len(cand) == 1:
        leftovers.remove(cand[0])
        return cand[0][3]
    return ''


def parse_options(boxes):
    result = _parse_options_before_r5(boxes)
    if result:
        return result
    if not boxes:
        return {}
    vals = {c: '' for c in _R5_ORDER}
    pos = {}
    leftovers = []
    for letter, x, y, h, text in _r5_parts(boxes):
        if letter in vals and letter not in pos:
            pos[letter] = x
            vals[letter] = text
        elif letter not in vals:
            leftovers.append((x, y, h, text))
    # marker present but empty value: one stray box in its slot
    for c in _R5_ORDER:
        if c in pos and not vals[c]:
            lo, hi = _r5_range(pos, c)
            vals[c] = _r5_take(leftovers, lo, hi)
    # marker dropped: exactly one letter missing, one box in its slot
    missing = [c for c in _R5_ORDER if c not in pos]
    if len(missing) == 1:
        lo, hi = _r5_range(pos, missing[0])
        vals[missing[0]] = _r5_take(leftovers, lo, hi)
    if all(vals[c] for c in _R5_ORDER):
        return clean_options(normalize_options({c: vals[c] for c in _R5_ORDER}))
    return {}


# ---- orchestrator integration adapter (no logic change): round 5 expects (x, y, h, text) items,
# but parse_options receives raw RapidOCR boxes; convert them with the module's reading_order().
_r5_parts_items = _r5_parts


def _r5_parts(boxes):
    return _r5_parts_items([(it["x"], it["y"], it["h"], it["text"]) for it in reading_order(boxes)])


# ---- orchestrator: pass order (own glue code, not a DeepSeek change) ----
# The round-5 rescue must not pre-empt the second OCR pass: strict parsing on the whole image,
# then strict parsing on the upscaled options band, and only then the rescue (band first).
def extract_options(image_bytes, boxes, ocr):
    boxes = boxes or []
    strict = _parse_options_before_r5
    options = strict(boxes)
    if options:
        return options
    band = _options_band(image_bytes, boxes)
    band_boxes = _cut_below_markers(ocr(band)[0] or []) if band is not None else []
    result = strict(band_boxes)
    if result:
        return result
    for rescued in (parse_options(band_boxes), parse_options(boxes)):
        values = [str(v).strip() for v in (rescued or {}).values()]
        if len(values) == 5 and all(values) and len(set(values)) == 5:  # five distinct values
            return rescued
    return {}
