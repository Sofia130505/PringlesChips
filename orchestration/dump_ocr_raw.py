"""Save the raw OCR text of each problem image, so the OCR improver can repair the options.

prepare_m3kang.py only caches the parsed options, not what OCR actually read.
This reruns RapidOCR and writes one line per problem to data/ocr_raw.jsonl:

  {"key": "lvl-0_2015_13|eng", "id": ..., "language": ..., "text": ...,
   "options": {...current parse...}, "ocr_lines": ["13. For 3 days ...", "(A) 12", ...],
   "flags": ["empty_options", "duplicate_values", ...]}

Each problem image is also saved to data/images/ and referenced as "image_path", so the
OCR improver (DeepSeek V4.1 Flash reads images) can look at the picture itself.
Labels are NOT written: the improver must never see the answer.

  python orchestration/dump_ocr_raw.py --languages eng,cat            # only problems that look broken
  python orchestration/dump_ocr_raw.py --languages eng,cat --all      # every problem
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "laptop"))
import prepare_m3kang as prep  # noqa: E402  (reuses its download and reading-order code)


def flags_for(text, options):
    flags = []
    if not options:
        flags.append("empty_options")
        return flags
    values = list(options.values())
    if len(set(values)) < len(values):
        flags.append("duplicate_values")
    nums = [v for v in values if re.fullmatch(r"-?\d+", v.replace(" ", ""))]
    if nums and any(len(v.replace(" ", "")) >= 3 for v in nums) and any("/" in text for _ in [0]):
        flags.append("maybe_fraction_lost")
    if any(len(v) > 40 for v in values):
        flags.append("long_option")
    if any(re.search(r"[^\w\s.,/%°²³+\-−×·:()√π=<>'\"€$]", v) for v in values):
        flags.append("odd_characters")
    return flags


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--languages", default="eng,cat")
    p.add_argument("--shards", default="0")  # same default as prepare_m3kang.py
    p.add_argument("--split", default="high_quality")
    p.add_argument("--all", action="store_true", help="dump every problem, not only flagged ones")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", default=os.path.join(ROOT, "data", "ocr_raw.jsonl"))
    args = p.parse_args()

    import pyarrow.parquet as pq

    # Reuse the OCR that prepare_m3kang.py already ran: its cache rows carry "lines".
    # OCR runs here only for problems missing from the cache (or cached without lines).
    cached = {}
    cache_path = os.path.join(ROOT, "data", ".ocr_cache.jsonl")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    if "lines" in row:
                        cached[row["key"]] = row
    print(f"{len(cached)} problems with cached OCR lines in {cache_path}")
    ocr = None
    reused = ran = 0

    done = set()
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            done = {json.loads(line)["key"] for line in f if line.strip()}
    out = open(args.out, "a", encoding="utf-8")

    shard_args = argparse.Namespace(shards=args.shards, split=args.split, parquet=None)
    languages = set(args.languages.split(","))
    n = kept = 0
    for path in prep.shard_paths(shard_args):
        langs = pq.read_table(path, columns=["language"]).column(0).to_pylist()
        wanted = [i for i, lang in enumerate(langs) if lang in languages]
        if not wanted:
            continue
        full = pq.read_table(path).take(wanted)
        for i in range(full.num_rows):
            if args.limit and n >= args.limit:
                break
            n += 1
            pid, lang = full.column("id")[i].as_py(), full.column("language")[i].as_py()
            key = f"{pid}|{lang}"
            if key in done:
                continue
            image = full.column("image")[i].as_py()["bytes"]
            if key in cached:
                options, lines = cached[key]["options"], cached[key]["lines"]
                reused += 1
            else:
                if ocr is None:
                    ocr = prep.make_ocr()  # GPU when available, same as prepare_m3kang.py
                boxes, _ = ocr(image)
                boxes = boxes or []
                # extract_options adds the second OCR pass on the options band and the
                # five-distinct-values check (parse_options alone would skip both).
                if hasattr(prep, "extract_options"):
                    options = prep.extract_options(image, boxes, ocr)
                else:
                    options = prep.parse_options(boxes)
                lines = [it["text"] for it in prep.reading_order(boxes)]
                ran += 1
            text = full.column("text")[i].as_py().strip()
            flags = flags_for(text, options)
            if not args.all and not flags:
                continue
            image_rel = os.path.join("data", "images", key.replace("|", "_") + ".png")
            os.makedirs(os.path.join(ROOT, "data", "images"), exist_ok=True)
            with open(os.path.join(ROOT, image_rel), "wb") as f:
                f.write(image)
            out.write(json.dumps({"key": key, "id": pid, "language": lang, "level": full.column("level")[i].as_py(),
                                  "text": text, "options": options, "ocr_lines": lines, "flags": flags,
                                  "image_path": image_rel.replace(os.sep, "/")},
                                 ensure_ascii=False) + "\n")
            out.flush()
            kept += 1
            if kept % 50 == 0:
                print(f"  {kept} written ({n} scanned)", flush=True)
    out.close()
    print(f"Done: {kept} new rows in {args.out} ({n} problems scanned; OCR reused {reused}, ran {ran})")


if __name__ == "__main__":
    main()
