#!/usr/bin/env python3
"""Appendix tables for the paper (paper/appendix_tables.tex).

Three tables: the full reconstruction matrix (rows from harness/build_tables.py over results/package/matrix.csv),
per-model totals, and the reasoning-effort ablation (copied verbatim from paper/tables.tex).
Default arguments reproduce the current file exactly (self-check before any change).
--with-kimi adds a Moonshot / Kimi K3 column and a per-model row computed from its run records; it requires
kimi-k3 to be present in results/package/matrix.csv (regenerate with harness/build_matrix.py first).
"""
import os
import pathlib
import argparse, glob, json, subprocess, sys
ROOT = os.environ.get("REVIVE_ROOT") or str(pathlib.Path(__file__).resolve().parents[1])
BASE_MODELS = "fable5.1,opus5,sonnet5,haiku4.5,gpt-5.6-sol,gpt-5.6-luna,gpt-5.6-terra,glm-5.3-flash"

STATIC_MODEL_ROWS = r"""Fable 5.1 & 13/13 & 13 & 20.8 & 95 \\
Opus 5 & 13/13 & 9 & 74.1 & 76 \\
Sonnet 5 & 10/13 & 13 & 60.1 & 35 \\
Haiku 4.5 & 2/13 & 15 & 80.3 & 15 \\
sol & 9/13 & 13 & 30.2 & n/a$^{\dagger}$ \\
luna & 6/13 & 13 & 35.3 & n/a$^{\dagger}$ \\
terra & 5/13 & 13 & 31.0 & n/a$^{\dagger}$ \\
GLM-5.3 flash & 7/13 & 13$^{\ddagger}$ & 83.1$^{\ddagger}$ & n/a$^{\dagger}$ \\"""


def kimi_row():
    """Engines passed, runs used, and mean turns over runs that record a turn count."""
    import csv
    M = {r["task"]: r for r in csv.DictReader(open(f"{ROOT}/results/package/matrix.csv"))}
    passed = sum(1 for r in M.values() if (r.get("kimi-k3") or "").startswith("PASS"))
    turns, used = [], 0
    for f in glob.glob(f"{ROOT}/runs/*/protocol__kimi-k3__m1/results.json"):
        d = json.load(open(f)); used += 1
        if d.get("num_turns"):
            turns.append(d["num_turns"])
    mean = f"{sum(turns) / len(turns):.1f}" if turns else "---"
    note = r"$^{\S}$" if len(turns) < used else ""
    return rf"Kimi K3 & {passed}/13 & {used} & {mean}{note} & n/a$^{{\dagger}}$ \\", len(turns), used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-kimi", action="store_true")
    ap.add_argument("--out", default=f"{ROOT}/paper/appendix_tables.tex")
    a = ap.parse_args()
    models = BASE_MODELS + (",kimi-k3" if a.with_kimi else "")
    rows = subprocess.run(["python3", f"{ROOT}/harness/build_tables.py", "--matrix",
                           f"{ROOT}/results/package/matrix.csv", "--models", models],
                          capture_output=True, text=True, check=True).stdout.strip()
    old = open(f"{ROOT}/paper/tables.tex").read()
    i = old.index(r"\caption{Reasoning-effort ablation"); b = old.rindex(r"\begin{table}[t]", 0, i)
    e = old.index(r"\end{table}", i) + len(r"\end{table}")
    # tables.tex is the pre-appendix layout: its effort caption still points at the old section label.
    effort = old[b:e].replace(r"(Section~\ref{sec:effort})", r"(Appendix~\ref{app:effort})")

    cols = r"ll cccc @{\hspace{1em}} ccc @{\hspace{1em}} c" + (r" @{\hspace{1em}} c" if a.with_kimi else "")
    groups = r"& & \multicolumn{4}{c}{Anthropic} & \multicolumn{3}{c}{OpenAI GPT-5.6} & Zhipu" + (r" & Moonshot" if a.with_kimi else "") + r" \\"
    rules = r"\cmidrule(lr){3-6}\cmidrule(lr){7-9}\cmidrule(lr){10-10}" + (r"\cmidrule(lr){11-11}" if a.with_kimi else "")
    names = r"Engine & Commercial analogue & Fable 5.1 & Opus 5 & Sonnet 5 & Haiku 4.5 & sol & luna & terra & GLM-5.3 flash" + (r" & Kimi K3" if a.with_kimi else "") + r" \\"
    kimi_caption = (r" Kimi K3 cells use a four-hour wall-clock limit (Section~\ref{sec:threats})." if a.with_kimi else "")
    matrix = (r"""\begin{table}[t]
\caption{Clean-room reconstruction of thirteen industrial software engines (the data behind
Figure~\ref{fig:results}a). Each cell is the hidden-verifier score of the best run under the
\emph{protocol} condition; scores are comparable \emph{within} a row only; \cmark{} denotes a pass.
GLM-5.3 flash cells use the runs described in Section~\ref{sec:threats}.""" + kimi_caption + r"""}
\label{tab:matrix}
\centering
\resizebox{\linewidth}{!}{%
\begin{tabular}{""" + cols + r"""}
\toprule
""" + groups + "\n" + rules + "\n" + names + r"""
\midrule
""" + rows.replace(r"\textbf{Engines passed}", "\\midrule\n\\textbf{Engines passed}", 1)
              + "\n\\bottomrule\\end{tabular}}\\end{table}\n")

    model_rows = STATIC_MODEL_ROWS
    extra_note = ""
    if a.with_kimi:
        row, n_turns, used = kimi_row()
        model_rows += "\n" + row
        if n_turns < used:
            extra_note = (rf"""
$^{{\S}}$ Over the {n_turns} of Kimi K3's {used} runs that record a turn count; the others ended at the
wall-clock limit.""")
    models_tbl = (r"""\begin{table}[t]
\caption{Per-model totals on the reconstruction suite. ``Engines passed'' is taken from
Table~\ref{tab:matrix}; runs, turns and cost are over all valid runs of that model.}
\label{tab:models}
\centering\small
\begin{tabular}{lrrrr}
\toprule
Model & Engines passed & Valid runs & Mean turns & Cost (USD) \\
\midrule
""" + model_rows + r"""
\bottomrule\end{tabular}
\\[2pt]\footnotesize $^{\dagger}$ Run through a local protocol adapter, so the harness prices them at the
launch model's rate; that figure is an artefact and is withheld. Token counts are genuine.
$^{\ddagger}$ The thirteen runs used in the matrix; four hit the wall-clock limit and record no turn
count, so the mean is over the other nine.""" + extra_note + r"""
\end{table}
""")
    open(a.out, "w").write(matrix + "\n" + models_tbl + "\n" + effort + "\n")
    print("written", a.out, "(with kimi)" if a.with_kimi else "")


if __name__ == "__main__":
    main()
