"""Append an OCR-improver round file to a candidate without name collisions.

  python orchestration/splice_fix.py <base_candidate.py> <round_file.py> <tag> <out.py>

Every top-level name the round file defines that already exists in the base (except
parse_options and the _parse_options_before_* hook, which are meant to replace/extend) is
renamed to _<tag>_<name> throughout the round file. Purely mechanical: no logic changes.
"""
import ast
import re
import sys

base_path, fix_path, tag, out_path = sys.argv[1:5]
base = open(base_path, encoding="utf-8").read()
fix = open(fix_path, encoding="utf-8").read()


def top_names(src):
    names = set()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


keep = {"parse_options", "extract_options"}
clash = sorted(n for n in top_names(fix) & top_names(base)
               if n not in keep and not n.startswith("_parse_options_before_"))
for name in clash:
    fix = re.sub(rf"(?<![\w.]){re.escape(name)}\b", f"_{tag}_{name.lstrip('_')}", fix)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(base + f"\n\n# ---- round {tag} (OCR improver) ----\n" + fix)
print(f"renamed {len(clash)} clashing names: {', '.join(clash) or '-'}")
