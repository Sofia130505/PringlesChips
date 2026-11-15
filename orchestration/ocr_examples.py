"""Build failing DEV examples for an OCR-improver brief (never test examples).

  python orchestration/ocr_examples.py work/ocr_eval/cand/r0_v2c.py --name r0 \
      --category "wrong: extra text glued on" -n 20 --out work/ocr_eval/r1_examples.md

For each example: the reading-order OCR items the parser saw (x, y, h, text) - the second-pass
band items when the first pass found nothing - what the code returned, and the expected options.
"""
import argparse
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "orchestration"))
import ocr_eval as ev  # noqa: E402


def items_seen(mod, image_bytes, boxes, ocr):
    """Which items produced the result: the first pass, or the band pass."""
    if mod.parse_options(boxes) or not hasattr(mod, "_options_band"):
        return "first pass (whole image)", mod.reading_order(boxes)
    band = mod._options_band(image_bytes, boxes)
    if band is None:
        return "first pass (whole image)", mod.reading_order(boxes)
    band_boxes, _ = ocr(band)
    if hasattr(mod, "_cut_below_markers"):
        band_boxes = mod._cut_below_markers(band_boxes or [])
    return "second pass (options band, upscaled)", mod.reading_order(band_boxes or [])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("candidate")
    p.add_argument("--name", required=True, help="results_<name>_dev.jsonl to read")
    p.add_argument("--category", required=True)
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    res = [r for r in ev.jl(os.path.join(ev.EVAL, f"results_{args.name}_dev.jsonl")) if r["category"] == args.category]
    random.seed(args.seed)
    pick = random.sample(res, min(args.n, len(res)))
    boxes = {r["key"]: r["boxes"] for r in ev.jl(ev.BOXES)}
    mod = ev.load_module(args.candidate, "cand_examples")
    ocr = ev.CachedOCR(mod.make_ocr)
    lines = [f"# {len(pick)} of {len(res)} dev failures in category '{args.category}' ({args.name})", ""]
    for r in pick:
        with open(ev.image_path(r["key"]), "rb") as f:
            img = f.read()
        source, items = items_seen(mod, img, boxes[r["key"]], ocr)
        lines.append(f"## {r['key']}  ({source})")
        lines.append("items (x, y, h, text), reading order, last 16:")
        for it in items[-16:]:
            lines.append(f"  ({it['x']:.0f}, {it['y']:.0f}, {it['h']:.0f}) {it['text']!r}")
        lines.append(f"code returned: {json.dumps(r['got'], ensure_ascii=False)}")
        lines.append(f"expected:      {json.dumps(r['expected'], ensure_ascii=False)}")
        lines.append("")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{len(pick)} examples -> {args.out}")


if __name__ == "__main__":
    main()
