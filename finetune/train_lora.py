"""LoRA SFT of Qwen3.5 0.8B on the M3Kang chat set, loss on the answer letter only.

The prompt is built from copilot.llm.SYSTEM + copilot.llm.format_problem() + "\nAnswer:"
and rendered with the model's chat template, so what the model sees here is what the
board sends with a grammar-restricted, max_tokens=1 request.

Letter bias: data/train_fixed.jsonl answers are skewed toward D (25%).  Every row whose
user text ends with a clean trailing "A) ... E)" block gets an extra copy whose option
texts are permuted and relabelled, with the correct option placed round-robin at
A,B,C,D,E so the copies are exactly uniform.  Rows without options cannot be shuffled
and keep their label.

  python finetune/train_lora.py --version ft-v1

Writes work/fine_tuner/lora_<version>/, letter_dist.json, val_metrics.json, train_<version>.log
Never reads data/val*.jsonl for training: it is only used for the final evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup
from peft import LoraConfig, get_peft_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from copilot.llm import SYSTEM, format_problem  # noqa: E402

# Base checkpoint: the original HF weights the Q8_0 GGUF in config.env was made from.
# CONFIRM THIS REPO ID ON huggingface.co BEFORE RUNNING (see finetune/README.md).
BASE_MODEL = "Qwen/Qwen3.5-0.8B"  # verified on huggingface.co: base of the board's GGUF
BASE_REVISION = "2fc06364715b967f1860aea9cf38778875588b17"  # pinned, like the other models in config.env

LETTERS = "ABCDE"
OPT_LINE = re.compile(r"^([A-E])\) (.*)$")
NO_OPTIONS_MARK = "(The options are in a picture that you can't see."
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# --------------------------------------------------------------------------- logging
class Log:
    def __init__(self, path=None):
        self.fh = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, *parts):
        msg = " ".join(str(p) for p in parts)
        print(msg, flush=True)
        if self.fh:
            self.fh.write(msg + "\n")
            self.fh.flush()


# ----------------------------------------------------------------------------- data

def _chat_ids(tok, messages, **kw):
    """Token ids from apply_chat_template: transformers 5 returns a BatchEncoding (dict-like),
    older versions a plain list. list() of the dict would give its key names."""
    out = tok.apply_chat_template(messages, **kw)
    if hasattr(out, "keys") and "input_ids" in out:
        out = out["input_ids"]
    return list(out)

def load_sft(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            ex = json.loads(line)
            msgs = ex["messages"]
            if [m["role"] for m in msgs] != ["system", "user", "assistant"]:
                raise SystemExit(f"line {i}: expected system/user/assistant, got {[m['role'] for m in msgs]}")
            if msgs[0]["content"] != SYSTEM:
                raise SystemExit(f"line {i}: system prompt drifted from copilot/llm.py")
            target = msgs[2]["content"].strip()
            if len(target) != 1 or target not in LETTERS:
                raise SystemExit(f"line {i}: target {target!r} is not one letter A-E")
            rows.append({"idx": i, "user": msgs[1]["content"], "label": target})
    return rows


def split_option_block(user_text):
    """(head_lines, {letter: option_text}) for a clean trailing A-E block, else (None, None)."""
    marker = "\nAnswer:"
    if not user_text.endswith(marker):
        return None, None
    lines = user_text[: -len(marker)].split("\n")
    if len(lines) < 5:
        return None, None
    head, tail = lines[:-5], lines[-5:]
    opts = {}
    for expected, line in zip(LETTERS, tail):
        m = OPT_LINE.match(line)
        if not m or m.group(1) != expected:
            return None, None
        opts[expected] = m.group(2)
    return head, opts


def shuffled_rows(rows, seed, copies=1):
    """Permute the option texts, place the correct one round-robin at A..E, remap label."""
    rng = random.Random(seed)
    out, counter = [], 0
    for row in rows:
        head, opts = split_option_block(row["user"])
        if head is None:
            continue
        gold_text = opts[row["label"]]
        for _ in range(copies):
            target = LETTERS[counter % len(LETTERS)]
            counter += 1
            others = [opts[k] for k in LETTERS if k != row["label"]]
            rng.shuffle(others)
            it = iter(others)
            new_opts = {k: (gold_text if k == target else next(it)) for k in LETTERS}
            user = "\n".join(head + [f"{k}) {new_opts[k]}" for k in LETTERS]) + "\nAnswer:"
            out.append({"idx": row["idx"], "user": user, "label": target, "aug": True})
    return out


def distribution(rows):
    c = Counter(r["label"] for r in rows)
    total = sum(c.values()) or 1
    d = {L: {"count": c.get(L, 0), "share": round(c.get(L, 0) / total, 4)} for L in LETTERS}
    d["total"] = total
    return d


# ------------------------------------------------------------------------ tokeniser
def assistant_end_tokens(tok):
    """The tokens the chat template puts after the assistant content (e.g. <|im_end|>)."""
    base = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    prompt = _chat_ids(tok, base, tokenize=True, add_generation_prompt=True)
    full = _chat_ids(tok, base + [{"role": "assistant", "content": "Z"}],
                                       tokenize=True)
    if full[: len(prompt)] != prompt:
        raise SystemExit("chat template is not prefix-stable; fix encode_example()")
    letter = tok.encode("Z", add_special_tokens=False)
    tail = full[len(prompt):]
    if tail[: len(letter)] != list(letter):
        raise SystemExit(f"unexpected assistant tail from the template: {tail}")
    return tail[len(letter):]


def prompt_ids(tok, user, max_len):
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    ids = _chat_ids(tok, msgs, tokenize=True, add_generation_prompt=True)
    return ids[:max_len]


class SFTDataset(Dataset):
    """Pre-tokenised rows: prompt ids masked to -100, then the letter and the turn end."""

    def __init__(self, rows, tok, max_len):
        self.end_tokens = assistant_end_tokens(tok)
        self.items = []
        self.too_long = 0
        for row in rows:
            ids = prompt_ids(tok, row["user"], max_len + 1)
            letter = tok.encode(row["label"], add_special_tokens=False)
            if len(letter) != 1:
                raise SystemExit(f"letter {row['label']!r} is not one token: {letter}")
            full = ids + letter + self.end_tokens
            if len(ids) > max_len or len(full) > max_len:
                self.too_long += 1
                continue
            labels = [-100] * len(ids) + letter + self.end_tokens
            self.items.append({"input_ids": full, "labels": labels})

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


def collate(batch, pad_id):
    n = max(len(b["input_ids"]) for b in batch)
    input_ids = torch.full((len(batch), n), pad_id, dtype=torch.long)
    labels = torch.full((len(batch), n), -100, dtype=torch.long)
    mask = torch.zeros((len(batch), n), dtype=torch.long)
    for i, b in enumerate(batch):
        L = len(b["input_ids"])
        input_ids[i, :L] = torch.tensor(b["input_ids"], dtype=torch.long)
        labels[i, :L] = torch.tensor(b["labels"], dtype=torch.long)
        mask[i, :L] = 1
    return {"input_ids": input_ids, "attention_mask": mask, "labels": labels}


# ------------------------------------------------------------------------ evaluation
def evaluate(model, tok, problems, letter_ids, batch_size, max_len, tag, log):
    """Greedy, one token restricted to A-E, exactly what the board's grammar allows."""
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    users = [format_problem(p) + "\nAnswer:" for p in problems]
    golds = [p.get("label", "").strip() for p in problems]
    preds = []
    model.eval()
    t0 = time.time()
    with torch.no_grad():
        for start in range(0, len(users), batch_size):
            chunk = users[start: start + batch_size]
            seqs = [prompt_ids(tok, u, max_len) for u in chunk]
            lens = [len(s) for s in seqs]
            n = max(lens)
            ids = torch.full((len(seqs), n), pad_id, dtype=torch.long, device=DEVICE)
            mask = torch.zeros((len(seqs), n), dtype=torch.long, device=DEVICE)
            for i, s in enumerate(seqs):
                ids[i, : len(s)] = torch.tensor(s, dtype=torch.long, device=DEVICE)
                mask[i, : len(s)] = 1
            out = model(input_ids=ids, attention_mask=mask)
            idx = torch.tensor(lens, dtype=torch.long, device=DEVICE) - 1
            last = out.logits[torch.arange(len(seqs), device=DEVICE), idx]
            picked = last.index_select(1, letter_ids).argmax(-1)
            preds.extend(LETTERS[int(v)] for v in picked.cpu())

    hit = Counter()
    conf = defaultdict(Counter)
    per_lang, per_level = defaultdict(Counter), defaultdict(Counter)
    for prob, gold, pred in zip(problems, golds, preds):
        if gold not in LETTERS:
            continue
        hit["n"] += 1
        hit["correct"] += int(pred == gold)
        conf[gold][pred] += 1
        lang = str(prob.get("language", "?"))
        per_lang[lang]["n"] += 1
        per_lang[lang]["correct"] += int(pred == gold)
        lvl = str(prob.get("level", "?"))
        per_level[lvl]["n"] += 1
        per_level[lvl]["correct"] += int(pred == gold)

    def pack(c):
        return {"n": c["n"], "correct": c["correct"],
                "accuracy": round(c["correct"] / c["n"], 4) if c["n"] else None}

    metrics = {
        "tag": tag,
        "n": hit["n"],
        "correct": hit["correct"],
        "accuracy": round(hit["correct"] / hit["n"], 4) if hit["n"] else None,
        "per_language": {k: pack(v) for k, v in sorted(per_lang.items())},
        "per_level": {k: pack(v) for k, v in sorted(per_level.items())},
        "predicted_letters": dict(Counter(preds)),
        "confusion": {g: dict(d) for g, d in sorted(conf.items())},
        "seconds": round(time.time() - t0, 1),
    }
    log(f"[eval:{tag}] accuracy {metrics['accuracy']} on {metrics['n']} rows "
        f"({metrics['seconds']} s)")
    return metrics


# ---------------------------------------------------------------------------- driver
def parse_args():
    p = argparse.ArgumentParser(description="LoRA SFT of Qwen3.5 0.8B for M3Kang")
    p.add_argument("--model", default=BASE_MODEL, help="original HF checkpoint (NOT the GGUF)")
    p.add_argument("--sft", default=os.path.join(ROOT, "work", "fine_tuner", "sft.jsonl"))
    p.add_argument("--val", default=os.path.join(ROOT, "data", "val_fixed.jsonl"))
    p.add_argument("--out-dir", default=os.path.join(ROOT, "work", "fine_tuner"))
    p.add_argument("--version", default="ft-v1")
    # augmentation
    p.add_argument("--shuffle-copies", type=int, default=1,
                   help="permuted copies per option row (0 disables the augmentation)")
    p.add_argument("--drop-originals", action="store_true",
                   help="train on the balanced shuffled copies only")
    # LoRA
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--alpha", type=int, default=32)
    p.add_argument("--dropout", type=float, default=0.05)
    p.add_argument("--targets", default="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj")
    # optimisation (defaults tuned for 8 GB)
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=2)
    p.add_argument("--max-len", type=int, default=512)
    p.add_argument("--warmup-ratio", type=float, default=0.03)
    p.add_argument("--weight-decay", type=float, default=0.0)
    p.add_argument("--grad-clip", type=float, default=1.0)
    p.add_argument("--grad-checkpointing", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--eval-batch-size", type=int, default=8)
    p.add_argument("--val-limit", type=int, default=0, help="0 = all validation rows")
    p.add_argument("--no-eval", action="store_true")
    p.add_argument("--log-every", type=int, default=20)
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    log = Log(os.path.join(args.out_dir, f"train_{args.version}.log"))

    if "val" in os.path.basename(args.sft).lower():
        raise SystemExit("Refusing to train on a validation file.")
    if "val" not in os.path.basename(args.val).lower():
        raise SystemExit(f"--val must point at a validation file, got {args.val}")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    log(f"== train_lora {args.version} | device {DEVICE} | torch {torch.__version__}")

    # ---- data + letter distribution ------------------------------------------------
    rows = load_sft(args.sft)
    n_no_options = sum(1 for r in rows if NO_OPTIONS_MARK in r["user"])
    aug = shuffled_rows(rows, args.seed, args.shuffle_copies) if args.shuffle_copies else []
    n_option_rows = len(rows) - n_no_options
    unshuffled = n_option_rows - (len(aug) // args.shuffle_copies if args.shuffle_copies else n_option_rows)
    train_rows = ([] if args.drop_originals else list(rows)) + aug
    random.Random(args.seed).shuffle(train_rows)

    dist_orig = distribution(rows)
    dist_train = distribution(train_rows)
    log(f"rows: {len(rows)} ({n_option_rows} with options, {n_no_options} without) "
        f"+ {len(aug)} shuffled copies -> {len(train_rows)} training examples"
        f" (unshuffled option rows: {unshuffled})")
    log("letter distribution before: " +
        " ".join(f"{L}={dist_orig[L]['count']}({100 * dist_orig[L]['share']:.1f}%)" for L in LETTERS))
    log("letter distribution after:  " +
        " ".join(f"{L}={dist_train[L]['count']}({100 * dist_train[L]['share']:.1f}%)" for L in LETTERS))
    with open(os.path.join(args.out_dir, "letter_dist.json"), "w", encoding="utf-8") as f:
        json.dump({"version": args.version,
                   "shuffle_copies": args.shuffle_copies,
                   "drop_originals": bool(args.drop_originals),
                   "rows_with_options": n_option_rows,
                   "rows_without_options": n_no_options,
                   "shuffled_copies": len(aug),
                   "before": dist_orig,
                   "after": dist_train}, f, indent=2)

    # ---- tokeniser -----------------------------------------------------------------
    tok = AutoTokenizer.from_pretrained(args.model, revision=BASE_REVISION)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    letter_ids = []
    for L in LETTERS:
        ids = tok.encode(L, add_special_tokens=False)
        if len(ids) != 1:
            raise SystemExit(f"letter {L!r} is not one token: {ids}")
        letter_ids.append(ids[0])
    letter_ids = torch.tensor(letter_ids, dtype=torch.long, device=DEVICE)
    end_tokens = assistant_end_tokens(tok)
    log(f"letter token ids: {dict(zip(LETTERS, letter_ids.tolist()))} | turn end: {end_tokens}")
    if {str(t) for t in end_tokens} & {tok.eos_token for tok in ()}:  # pragma: no cover
        pass

    # ---- validation set (never trained on) -----------------------------------------
    val = []
    with open(args.val, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                val.append(json.loads(line))
    if args.val_limit:
        val = val[: args.val_limit]
    prompt_hash = hashlib.sha256(
        ("\n".join([SYSTEM, format_problem(val[0]) + "\nAnswer:"])).encode("utf-8")
    ).hexdigest()
    log(f"validation rows: {len(val)} (prompt sha256 {prompt_hash[:16]}…)")

    # ---- base model ----------------------------------------------------------------
    dtype = torch.bfloat16 if (DEVICE == "cuda" and torch.cuda.is_bf16_supported()) else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=BASE_REVISION, torch_dtype=dtype, attn_implementation="sdpa", low_cpu_mem_usage=True)
    model.config.use_cache = False
    model.to(DEVICE)
    log(f"loaded {args.model} in {str(dtype).replace('torch.', '')}")

    base_metrics = None
    if not args.no_eval:
        base_metrics = evaluate(model, tok, val, letter_ids, args.eval_batch_size,
                                args.max_len, "base", log)

    # ---- LoRA ----------------------------------------------------------------------
    lora = LoraConfig(
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=args.dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[t.strip() for t in args.targets.split(",") if t.strip()],
    )
    model = get_peft_model(model, lora)
    if args.grad_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    model.print_trainable_parameters()
    model.to(DEVICE)

    train_ds = SFTDataset(train_rows, tok, args.max_len)
    if train_ds.too_long:
        log(f"skipped {train_ds.too_long} examples longer than {args.max_len} tokens")
    if not len(train_ds):
        raise SystemExit("no training examples left after length filtering")
    loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0,
                        collate_fn=lambda b: collate(b, tok.pad_token_id),
                        generator=torch.Generator().manual_seed(args.seed), drop_last=False)

    steps_per_epoch = max(1, len(loader) // args.grad_accum)
    total_steps = max(1, int(steps_per_epoch * args.epochs))
    optim = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                              lr=args.lr, betas=(0.9, 0.999), eps=1e-8,
                              weight_decay=args.weight_decay)
    sched = get_cosine_schedule_with_warmup(
        optim, int(total_steps * args.warmup_ratio), total_steps)
    log(f"steps/epoch {steps_per_epoch}, total {total_steps}, "
        f"effective batch {args.batch_size * args.grad_accum}")

    # ---- training loop -------------------------------------------------------------
    model.train()
    t0 = time.time()
    global_step, micro, running, seen = 0, 0, 0.0, 0
    optim.zero_grad(set_to_none=True)
    for epoch in range(1, int(args.epochs) + 1):
        for batch in loader:
            batch = {k: v.to(DEVICE) for k, v in batch.items()}
            out = model(**batch)
            loss = out.loss / args.grad_accum
            loss.backward()
            running += float(out.loss)
            micro += 1
            seen += batch["input_ids"].shape[0]
            if micro % args.grad_accum == 0 or micro == len(loader):
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], args.grad_clip)
                optim.step()
                sched.step()
                optim.zero_grad(set_to_none=True)
                global_step += 1
                if global_step % args.log_every == 0:
                    el = time.time() - t0
                    log(f"epoch {epoch} step {global_step}/{total_steps} "
                        f"loss {running / args.log_every:.4f} lr {sched.get_last_lr()[0]:.2e} "
                        f"{seen / max(el, 1e-6):.1f} ex/s")
                    running = 0.0
        log(f"--- epoch {epoch} done at {time.time() - t0:.0f} s "
            f"({seen} examples)")
        running = 0.0
    train_seconds = time.time() - t0
    log(f"training finished in {train_seconds / 60:.1f} min")

    # ---- save adapter --------------------------------------------------------------
    adapter_dir = os.path.join(args.out_dir, f"lora_{args.version}")
    model.save_pretrained(adapter_dir)
    tok.save_pretrained(adapter_dir)
    with open(os.path.join(adapter_dir, "run_config.json"), "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "base_model": args.model, "base_model_confirmed": False,
                   "n_train": len(train_ds), "steps": global_step,
                   "effective_batch": args.batch_size * args.grad_accum,
                   "train_seconds": round(train_seconds, 1),
                   "torch": torch.__version__, "device": torch.cuda.get_device_name(0)
                   if DEVICE == "cuda" else torch.cuda.get_device_name(0)},
                  f, indent=2)
    log(f"adapter saved to {adapter_dir}")

    # ---- final evaluation ----------------------------------------------------------
    if args.no_eval:
        return
    ft_metrics = evaluate(model, tok, val, letter_ids, args.eval_batch_size,
                          args.max_len, "finetuned", log)
    delta = None
    if base_metrics and base_metrics["accuracy"] is not None:
        delta = round(ft_metrics["accuracy"] - base_metrics["accuracy"], 4)
        log(f"[eval] base {base_metrics['accuracy']:.4f} -> "
            f"ft {ft_metrics['accuracy']:.4f} ({delta:+.4f})")

    metrics_path = os.path.join(args.out_dir, "val_metrics.json")
    payload = {
        "version": args.version,
        "base_model": args.model,
        "base_model_confirmed": False,
        "val_file": os.path.relpath(args.val, ROOT),
        "val_prompt_sha256": prompt_hash,
        "letter_token_ids": dict(zip(LETTERS, letter_ids.tolist())),
        "train": {
            "sft_file": os.path.relpath(args.sft, ROOT),
            "n_examples": len(train_ds),
            "epochs": args.epochs,
            "effective_batch": args.batch_size * args.grad_accum,
            "steps": global_step,
            "seconds": round(train_seconds, 1),
            "lora": {"r": args.rank, "alpha": args.alpha, "dropout": args.dropout},
            "letter_distribution_before": dist_orig,
            "letter_distribution_after": dist_train,
        },
        "base": base_metrics,
        "finetuned": ft_metrics,
        "delta_accuracy": delta,
    }
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    log(f"metrics written to {metrics_path}")


if __name__ == "__main__":
    main()
