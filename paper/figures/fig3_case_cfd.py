"""Figure 3: case study -- the CFD verifier graded a self-reported number.

Every number is re-derived (2026-09-13) from the run directories:
  * luna's Taylor-Green branch: runs/cfd_solver/protocol__gpt-5.6-luna__p1/workspace/flowx.py:58
    `out["max|∇·u|"] = 0.0`; velocities from math.sin/math.cos closed forms, no grid.
  * solver lines = raw lines of *.py excluding tests/, examples/, verify*.py, test_*.py, venv/, .git/,
    for the run the model matrix selects (results/package/matrix_provenance.csv):
    fable5.1 m1 1115 · opus5 m2 1560 · sonnet5 m2 477 · gpt-5.6-sol p1 292 · gpt-5.6-luna p1 134.
  * verifier scores: matrix.csv cfd_solver row. The key-rename replication is reported without a
    denominator on purpose: it ran against an earlier check set, so "5/5" is not comparable to "x/6".
Palette: emphasis form -- one highlighted series (orange, categorical slot 2), the rest muted gray.
"""
import os
import os, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

INK, INK2, MUTED, HAIR, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
ORANGE = "#eb6834"
avail = {f.name for f in font_manager.fontManager.ttflist}
FONT = next(c for c in ("Helvetica", "Arial", "Liberation Sans", "Nimbus Sans", "DejaVu Sans") if c in avail)
MONO = next(c for c in ("Nimbus Mono PS", "Liberation Mono", "DejaVu Sans Mono") if c in avail)
SYM = "DejaVu Sans"
plt.rcParams.update({"font.family": [FONT, "DejaVu Sans"], "pdf.fonttype": 42})

fig = plt.figure(figsize=(11, 3.1), dpi=200)
ax = fig.add_axes([0, 0, 0.70, 1]); ax.set_xlim(0, 77); ax.set_ylim(0, 31); ax.axis("off")

def card(x, y, w, h, ec=HAIR, lw=0.8, r=0.9):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc="white", ec=ec, lw=lw, zorder=1))

steps = [
    ("1", "Spec prints answers", ["Closed forms are given so", "agents can self-check:", "Poiseuille, Taylor–Green,", "Burgers"], None),
    ("2", "A 134-line \"solver\"", ["No grid, no time stepping;", "velocities evaluated from", "the closed forms."], 'out["max|∇·u|"] = 0.0'),
    ("3", "Verifier: full marks", ["Rename one output key,", "change no numerics:", "accuracy 13/13 · ∇·u 2/2", "flux 2/2 · shock 2/2"], None),
    ("4", "Root cause", ["The check read the reported", "|∇·u| ≤ 1e-8 instead of", "recomputing it from the", "candidate's own fields."], None),
]
W, H, Y, GAP = 17.4, 20.0, 4.6, 1.7
for i, (num, title, lines, code) in enumerate(steps):
    x = 0.6 + i * (W + GAP)
    hot = i in (1, 2)
    card(x, Y, W, H, ec=ORANGE if hot else HAIR, lw=1.1 if hot else 0.8)
    ax.text(x + 1.0, Y + H - 2.3, num, fontsize=9.4, color=MUTED, fontweight="bold", va="center")
    ax.text(x + 2.7, Y + H - 2.3, title, fontsize=8.8, color=INK, fontweight="bold", va="center")
    for k, ln in enumerate(lines):
        ax.text(x + 1.0, Y + H - 5.6 - k * 2.25, ln, fontsize=7.2, color=INK2, va="center")
    if code:
        cy = Y + 3.2
        ax.add_patch(FancyBboxPatch((x + 0.9, cy - 1.45), W - 1.8, 2.9, boxstyle="round,pad=0,rounding_size=0.5",
                                    fc="#f3f2ee", ec="none", zorder=2))
        ax.text(x + W / 2, cy, code, fontsize=7.0, color=INK, family=[MONO, "DejaVu Sans Mono"], ha="center", va="center", zorder=3)
    if i == 2:
        ax.text(x + W / 2, Y + 3.2, "PASS", fontsize=12, color=INK, fontweight="bold", ha="center", va="center")
    if i < 3:
        ax.add_patch(FancyArrowPatch((x + W + 0.15, Y + H / 2), (x + W + GAP - 0.15, Y + H / 2),
                                     arrowstyle="-|>", mutation_scale=10, color=MUTED, lw=1.3, zorder=4))
ax.text(0.6, 27.9, "The CFD task awarded full marks to a program that does no numerics",
        fontsize=11, color=INK, fontweight="bold", va="center")
ax.text(0.6, 2.0, "Fix: never grade a self-reported quantity; recompute it from the candidate's own output, "
        "as the place-and-route verifier already did.", fontsize=7.2, color=INK2, va="center")

# ---------------- right: code size vs. score ----------------
bx = fig.add_axes([0.765, 0.2, 0.205, 0.6])
models = ["Fable 5.1", "Opus 5", "Sonnet 5", "GPT-5.6 sol", "GPT-5.6 luna"]
loc = [1115, 1560, 477, 292, 134]
score = ["6/6", "6/6", "6/6", "4/6", "4/6 → pass*"]
yy = list(range(len(models)))[::-1]
bx.barh(yy, loc, height=0.5, color=[BASE] * 4 + [ORANGE], zorder=2)
for yi, v, s in zip(yy, loc, score):
    bx.text(v + 40, yi, f"{v:,} · {s}", fontsize=7.0, color=INK, va="center")
bx.set_yticks(yy); bx.set_yticklabels(models, fontsize=7.4, color=INK)
bx.set_xlim(0, 2500); bx.set_xticks([0, 500, 1000, 1500]); bx.tick_params(axis="x", labelsize=6.8, colors=MUTED, length=0)
bx.tick_params(axis="y", length=0)
for s in ("top", "right", "left"): bx.spines[s].set_visible(False)
bx.spines["bottom"].set_color(BASE); bx.spines["bottom"].set_linewidth(0.8)
bx.grid(axis="x", color=HAIR, lw=0.6, zorder=0)
fig.text(0.765, 0.88, "Solver lines · verifier score", fontsize=9, color=INK, fontweight="bold")
fig.text(0.765, 0.065, "* after renaming one output key", fontsize=6.8, color=INK2)

out = f"{ROOT}/paper/figures/fig3_case_cfd"
fig.savefig(out + ".pdf", facecolor="white")
fig.savefig(out + ".png", dpi=200, facecolor="white")
print("fonts:", FONT, MONO, "->", out + ".pdf/.png")
