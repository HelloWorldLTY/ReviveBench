#!/usr/bin/env python3
"""Revival results table for the paper (paper/tab_revival.tex), generated from runs/<task>/*/results.json.

Reads run records directly (results/package/runs.csv is a static 215-row snapshot and misses later runs).
Model names are normalised to the underlying model, verified from each trajectory's init event:
  "sonnet" (Anthropic endpoint, 2026-09-08) and "sonnet5" (Bedrock) are both claude-sonnet-5;
  "haiku" and "haiku4.5" are both claude-haiku-4-5-20251001; "fable" is claude-fable-5-1.

Cell = passed runs / all runs of that model on that task (all conditions except the no-agent baseline,
interrupted runs included, since several interrupted runs had already restored the software).
"—" = the model was not run on that task.
"""
import os
import pathlib
import csv, collections
ROOT = os.environ.get("REVIVE_ROOT") or str(pathlib.Path(__file__).resolve().parents[1])
GROUPS = [
    ("Dependency rot", [("deepimpute_keras3", "deepimpute", "TF~2.16 / Keras~3 / NumPy~2"),
                        ("dca_keras3", "DCA", "removed Keras and TF-1 APIs")]),
    ("Deleted core module", [("deepimpute_reconstruct", "deepimpute", "core module deleted"),
                             ("deepimpute_reconstruct_obf", "deepimpute (obf.)", "same, identifiers renamed")]),
    ("Build and reproduce", [("pymol_modern", "PyMOL 2.3", "2019 C++ build, Python~3.12"),
                             ("qupath_modern", "QuPath 0.2.3", "Java~14 build, JDK~21"),
                             ("caduceus_modern", "Caduceus", "GPU Mamba kernels, torch~$\\geq$2.5")]),
    ("Post-cutoff (2026)", [("binderranker_reconstruct2026", "binderranker", "module deleted, tests hidden"),
                            ("interelate_reconstruct2026", "interelate", "module deleted, tests hidden"),
                            ("sirna_data_grabber_reconstruct2026", "sirna\\_data", "module deleted, tests hidden")]),
]
MODELS = ["fable", "sonnet", "haiku"]
import glob, json
NORM = {"fable": "fable", "fable5.1": "fable", "sonnet": "sonnet", "sonnet5": "sonnet",
        "haiku": "haiku", "haiku4.5": "haiku"}
TASKS = {t for _, rows in GROUPS for t, _, _ in rows}
agg = collections.defaultdict(lambda: [0, 0])
for f in glob.glob(f"{ROOT}/runs/*/*/results.json"):
    task = f.split("/")[-3]
    if task not in TASKS:
        continue
    d = json.load(open(f))
    if d.get("condition") == "noagent":
        continue
    m = NORM.get(d.get("model"))
    if m is None:
        continue
    a = agg[(task, m)]; a[0] += bool(d.get("post_pass")); a[1] += 1
lines = [r"\begin{table}[t]",
         r"\caption{Software revival. Each cell is passed runs / all runs of that model on that task; ``---'' means the model",
         r"was not run on the task. Every starting workspace fails its verifier. The models are the same Fable~5.1, Sonnet~5",
         r"and Haiku~4.5 used in the reconstruction suite, reached through Anthropic's own endpoint or, for eight later runs, Amazon Bedrock.}",
         r"\label{tab:revival}", r"\centering\small",
         r"\resizebox{\linewidth}{!}{%", r"\begin{tabular}{lllccc}", r"\toprule",
         r"Category & Software & What is broken & Fable 5.1 & Sonnet 5 & Haiku 4.5 \\", r"\midrule"]
tot = {m: [0, 0, 0, 0] for m in MODELS}
for gi, (gname, rows) in enumerate(GROUPS):
    if gi:
        lines.append(r"\addlinespace[2pt]")
    for k, (task, sw, broken) in enumerate(rows):
        cells = []
        for m in MODELS:
            p, n = agg[(task, m)]
            cells.append(f"{p}/{n}" if n else "---")
            if n:
                tot[m][0] += p; tot[m][1] += n; tot[m][2] += p > 0; tot[m][3] += 1
        lines.append(" & ".join([gname if k == 0 else "", sw, broken] + cells) + r" \\")
lines.append(r"\midrule")
lines.append(" & ".join([r"\textbf{Tasks restored}", "", ""] + [rf"\textbf{{{tot[m][2]}/{tot[m][3]}}}" for m in MODELS]) + r" \\")
lines += [r"\bottomrule\end{tabular}}\end{table}"]
open(f"{ROOT}/paper/tab_revival.tex", "w").write("\n".join(lines) + "\n")
print("tab_revival.tex written; tasks restored/attempted:", {m: f"{tot[m][2]}/{tot[m][3]}" for m in MODELS},
      "runs passed/total:", {m: f"{tot[m][0]}/{tot[m][1]}" for m in MODELS})
