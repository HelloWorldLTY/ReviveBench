"""Figure 1: ReviveBench overview (tasks -> agent -> hidden verifier, plus verifier auditing).

Light-only by design: a static PDF figure for a printed paper.
Palette: reference data-viz categorical slots 1-3 (validated all-pairs, light):
  blue #2a78d6 (tasks), aqua #1baf7a (agent), orange #eb6834 (verifier) -- low-opacity panel
  washes and small accents only; all text uses ink tokens.
Engine grouping follows each task's verifier check names (runs/*/results.json post_checks):
  tolerance: stats LRE, SPICE waveforms, FE fields, 2D CAD geometry, CFD analytic accuracy
  exact / proof: synthesis SAT equivalence, 3D exact topology + membership, PLC exact traces,
                 place & route legality + connectivity
  invariants: ERP ledger, SCADA event journal, MES schedule/genealogy, PLM BOM queries
"""
import os
import os, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

N_MODELS_LABEL = "8 models · 3 vendors"      # includes GLM-5.3 flash (capped m4 reruns)

INK, INK2, MUTED, HAIR = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, AQUA, ORANGE = "#2a78d6", "#1baf7a", "#eb6834"

avail = {f.name for f in font_manager.fontManager.ttflist}
FONT = next(c for c in ("Helvetica", "Arial", "Liberation Sans", "Nimbus Sans", "TeX Gyre Heros", "DejaVu Sans") if c in avail)
plt.rcParams.update({"font.family": [FONT, "DejaVu Sans"], "pdf.fonttype": 42})
SYM = "DejaVu Sans"   # glyphs ≈ ⊢ = → χ

fig = plt.figure(figsize=(11, 4.95), dpi=200)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 110); ax.set_ylim(-4.2, 46); ax.axis("off")

def panel(x, y, w, h, hue, alpha=0.08, r=1.4):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=hue, ec="none", alpha=alpha, zorder=0))

def card(x, y, w, h, r=0.9, fc="white", ec=HAIR, lw=0.8, z=1):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec=ec, lw=lw, zorder=z))

def chip(x, y, text, w, h=2.3, fs=7.2):
    card(x, y, w, h, r=0.55, z=2)
    ax.text(x + w / 2, y + h / 2, text, fontsize=fs, color=INK, va="center", ha="center", zorder=3)

def header(x, y, num, title, sub):
    ax.text(x, y, num, fontsize=10, color=MUTED, fontweight="bold", va="baseline")
    ax.text(x + 2.2, y, title, fontsize=12.5, color=INK, fontweight="bold", va="baseline")
    ax.text(x, y - 2.1, sub, fontsize=8.2, color=INK2, va="baseline")

def arrow(x0, y0, x1, y1, color=MUTED, lw=1.6):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=12,
                                 color=color, lw=lw, zorder=4))

# ---------------- Panel 1: tasks ----------------
panel(1, 1, 38, 44, BLUE)
header(2.5, 41.2, "1", "Tasks", "software that does not run, or does not exist")

card(2.5, 22.4, 35, 15.4)
ax.text(3.6, 35.6, "Software revival", fontsize=9.6, fontweight="bold", color=INK)
ax.text(36.4, 35.6, "10 tasks", fontsize=8.2, color=INK2, ha="right")
rows = [("Dependency rot · Keras 3, NumPy 2", "Deleted core module"),
        ("2019 C++ build → Python 3.12", "Java 14 → JDK 21"),
        ("GPU foundation model", "Post-cutoff repos (2026)")]
for i, (a, b) in enumerate(rows):
    yy = 31.6 - i * 2.95
    chip(3.6, yy, a, 18.8)
    chip(23.0, yy, b, 13.4)
ax.text(3.6, 23.3, "every starting workspace fails its verifier", fontsize=7.4, color=INK2, style="italic")

card(2.5, 2.2, 35, 19.2)
ax.text(3.6, 19.2, "Clean-room reconstruction", fontsize=9.6, fontweight="bold", color=INK)
ax.text(36.4, 19.2, "13 engines", fontsize=8.2, color=INK2, ha="right")
ax.text(3.6, 17.2, "spec + 3 worked examples · existing implementations forbidden", fontsize=7.2, color=INK2)
groups = [("≈", "numerical tolerance", ["Statistics", "SPICE", "FE solver", "2D CAD", "CFD / CAE"]),
          ("⊢", "exact or proof", ["PLC runtime", "Logic synth.", "3D solid", "Place & route"]),
          ("=", "transactional invariants", ["ERP", "SCADA", "MES", "PLM"])]
top = 15.1
for g, (sym, label, names) in enumerate(groups):
    ly = top - g * 4.35
    ax.text(3.6, ly, sym, fontsize=8.4, color=MUTED, va="center")
    ax.text(5.0, ly, label, fontsize=7.2, color=INK2, va="center")
    n = len(names); gap = 0.55; w = (32.8 - gap * (n - 1)) / n
    for k, name in enumerate(names):
        chip(3.6 + k * (w + gap), ly - 3.05, name, w, h=2.2, fs=7.0)

# ---------------- Panel 2: agent ----------------
panel(42, 1, 25, 44, AQUA)
header(43.5, 41.2, "2", "Agent", "headless coding agent in a sandbox")
card(43.5, 22.4, 22, 15.4)
ax.text(54.5, 35.4, "Claude Code harness", fontsize=9.4, fontweight="bold", color=INK, ha="center")
ax.text(54.5, 33.3, N_MODELS_LABEL, fontsize=8, color=INK2, ha="center")
for i, t in enumerate(["own virtual environment per run", "fixed turn budget per task",
                       "forbidden packages checked", "verifier, data, thresholds hidden"]):
    yy = 30.4 - i * 2.2
    ax.add_patch(plt.Circle((45.2, yy), 0.32, color=AQUA, zorder=3))
    ax.text(46.2, yy, t, fontsize=7.6, color=INK, va="center")
card(43.5, 11.8, 22, 9.6)
ax.text(54.5, 19.3, "What we record", fontsize=9, fontweight="bold", color=INK, ha="center")
for i, t in enumerate(["full trajectory", "code diff vs. root commit", "tokens · turns · wall time"]):
    ax.text(54.5, 17.0 - i * 1.95, t, fontsize=7.6, color=INK2, ha="center", va="center")
card(43.5, 2.2, 22, 8.6)
ax.text(54.5, 8.8, "No-agent baseline", fontsize=9, fontweight="bold", color=INK, ha="center")
ax.text(54.5, 6.5, "run for every task", fontsize=7.6, color=INK2, ha="center", va="center")
ax.text(54.5, 4.6, "and fails everywhere", fontsize=7.6, color=INK2, ha="center", va="center")

# ---------------- Panel 3: verifier ----------------
panel(70, 1, 39, 44, ORANGE)
header(71.5, 41.2, "3", "Hidden verifier", "three incompatible notions of correctness")
notions = [("≈", "Numerical tolerance", "NIST StRD LRE · ngspice waveforms · CalculiX fields · closed forms"),
           ("⊢", "Exact or proof", "Yosys SAT miter · Euler χ + shells · PLC traces · routing legality"),
           ("=", "Transactional invariants", "after every document · integer cents · exact event journals")]
for i, (sym, title, ex) in enumerate(notions):
    yy = 33.0 - i * 4.9
    card(71.5, yy, 36, 4.2)
    ax.text(72.9, yy + 2.1, sym, fontsize=13, color=INK2, va="center")
    ax.text(75.4, yy + 2.85, title, fontsize=8.8, fontweight="bold", color=INK, va="center")
    ax.text(75.4, yy + 1.15, ex, fontsize=6.9, color=INK2, va="center")

card(71.5, 2.2, 36, 20.2, ec=ORANGE, lw=1.1)
ax.text(72.8, 19.9, "Auditing the verifier", fontsize=9.6, fontweight="bold", color=INK)
ax.text(106.2, 19.9, "28 defects", fontsize=9.6, fontweight="bold", color=INK, ha="right")
ax.text(106.2, 17.8, "incl. 24 false negatives · 2 false positives", fontsize=7.2, color=INK2, ha="right")
for i, (t, d) in enumerate([("Achievability probe", "solve each case the way the spec prescribes"),
                            ("Consensus among candidates", "agents agree, oracle disagrees → suspect the asset"),
                            ("Never grade self-reports", "recompute from the candidate's own artefact")]):
    yy = 14.3 - i * 4.0
    ax.add_patch(plt.Circle((73.2, yy), 0.36, color=ORANGE, zorder=3))
    ax.text(74.4, yy + 0.2, t, fontsize=8.2, fontweight="bold", color=INK, va="bottom")
    ax.text(74.4, yy - 0.35, d, fontsize=7.1, color=INK2, va="top")

# ---------------- flow ----------------
arrow(39.3, 30.0, 42.2, 30.0)
arrow(39.3, 11.8, 42.2, 11.8)
arrow(67.3, 30.0, 70.2, 30.0)
# feedback loop routed below the panels
FB = -1.4
ax.plot([89.5, 89.5, 20.0], [1.0, FB, FB], color=ORANGE, lw=1.0, linestyle=(0, (3, 2)), zorder=4,
        solid_capstyle="round")
arrow(20.0, FB, 20.0, 0.9, color=ORANGE, lw=1.0)
ax.text(54.75, -3.1, "defect fixed  →  re-score if the spec is unchanged, re-run if the spec gained information",
        fontsize=7.2, color=INK2, ha="center", va="center")

out = f"{ROOT}/paper/figures/fig1_overview"
fig.savefig(out + ".pdf", facecolor="white")
fig.savefig(out + ".png", dpi=200, facecolor="white")
print("font:", FONT, "->", out + ".pdf/.png")
