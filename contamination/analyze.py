#!/usr/bin/env python3
"""Contamination analysis: (a) similarity of reconstructed modules to the original (recall signal),
(b) restore rates by cohort: pre-cutoff original / pre-cutoff obfuscated / post-cutoff 2026 packages."""
import os
import pathlib
import difflib, json, pathlib, re, tarfile, collections
ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
def norm(s):
    out = []
    for l in s.splitlines():
        l = re.sub(r"#.*", "", l).strip()
        if l: out.append(re.sub(r"\s+", " ", l))
    return out
def sim(orig, src):
    O, S = norm(orig), norm(src); sm = difflib.SequenceMatcher(None, O, S)
    return round(sm.ratio(), 3), round(sum(1 for l in S if l in set(O)) / max(1, len(S)), 3), len(S)
with tarfile.open(ROOT / "tasks/deepimpute_keras3/hidden/pristine/repo.tar.gz") as t:
    orig = t.extractfile("deepimpute/multinet.py").read().decode()
MAP = json.loads((ROOT / "tasks/deepimpute_reconstruct_obf/task.json").read_text())["obfuscation_map"]
def deobf(s):  # map obfuscated names back so similarity to the original is comparable
    for a, b in MAP: s = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(b) + r"(?![A-Za-z0-9_])", a, s)
    return s
rows = []
print(f"{'run':55s} {'pass':5s} seqratio exact_line lines")
for task, rel in [("deepimpute_reconstruct", "deepimpute/multinet.py"), ("deepimpute_reconstruct_obf", "gapfill/subnet.py")]:
    for r in sorted(ROOT.glob(f"runs/{task}/*/results.json")):
        d = json.loads(r.read_text()); f = r.parent / "workspace" / rel
        if d["condition"] == "noagent" or not f.exists(): continue
        src = f.read_text(); src = deobf(src) if "obf" in task else src
        s = sim(orig, src); rows.append({"task": task, "run": r.parent.name, "pass": d["post_pass"], "seqratio": s[0], "exact": s[1], "lines": s[2], "cost": d.get("cost_usd")})
        print(f"{task + '/' + r.parent.name:55s} {str(d['post_pass']):5s} {s[0]:.3f}    {s[1]:.3f}      {s[2]}")
print()
allrows = json.loads((ROOT / "results/summary.json").read_text())
coh = collections.defaultdict(list)
for d in allrows:
    if d["condition"] == "noagent" or (d.get("interrupted") and not d["post_pass"]) or d.get("max_turns", 0) < 80: continue
    t = json.loads((ROOT / "tasks" / d["task"] / "task.json").read_text())
    cohort = t.get("cohort", "obfuscated" if "obf" in d["task"] else "pre-cutoff")
    coh[(cohort, d["model"])].append(d["post_pass"])
print(f"{'cohort':22s} {'model':8s} n  restore")
for (c, m), v in sorted(coh.items()):
    print(f"{c:22s} {m:8s} {len(v):<2d} {sum(v)}/{len(v)}")
json.dump({"similarity": rows, "cohorts": {f"{c}|{m}": [sum(v), len(v)] for (c, m), v in coh.items()}}, open(ROOT / "contamination" / "analysis.json", "w"), indent=1)
