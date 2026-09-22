"""Figure 2: results. (a) clean-room engine matrix; (b) revival contamination controls.

Sources (all programmatic, no hand-typed scores):
  (a) harness/build_matrix.py (7-model matrix; add --with-glm once GLM's capped m4 runs finish).
  (b) the report's embedded data (results/ReviveBench_技术报告.html, <script id="R">):
      contamination.cohorts and contamination.similarity.
Palette (validated with the data-viz validator):
  heatmap: blue ordinal ramp #86b6ef #5598e7 #2a78d6 #1c5cab #104281 (ALL PASS, --ordinal).
           PASS cells take the darkest step; FAIL cells use the four lighter steps by within-row
           fraction, so pass/fail reads at a glance and the ✓ is a second channel, not the only one.
  revival: categorical slots 1-3 #2a78d6 #eb6834 #1baf7a (ALL PASS all-pairs; aqua contrast WARN ->
           every model is direct-labelled).
"""
import os
import pathlib
import csv, json, re, subprocess, sys, tempfile, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

ROOT = os.environ.get("REVIVE_ROOT") or str(pathlib.Path(__file__).resolve().parents[2])
MODELS = [("fable5.1", "Fable 5.1"), ("opus5", "Opus 5"), ("sonnet5", "Sonnet 5"), ("haiku4.5", "Haiku 4.5"),
          ("gpt-5.6-sol", "sol"), ("gpt-5.6-luna", "luna"), ("gpt-5.6-terra", "terra")]
VENDORS = [("Anthropic", 4), ("OpenAI GPT-5.6", 3)]
if "--with-glm" in sys.argv:
    MODELS.append(("glm-5.3-flash", "GLM-5.3 flash")); VENDORS.append(("Zhipu", 1))
if "--with-kimi" in sys.argv:
    MODELS.append(("kimi-k3", "Kimi K3")); VENDORS.append(("Moonshot", 1))

GROUPS = [("≈  numerical tolerance", [("stats_nist", "Statistics"), ("spice_ngspice", "SPICE"), ("fem_nafems", "FE solver"),
                                      ("cad2d_dxf", "2D CAD"), ("cfd_solver", "CFD / CAE")]),
          ("⊢  exact or proof", [("plc_iec61131", "PLC runtime"), ("synth_verilog", "Logic synthesis"),
                                 ("cad3d_brep", "3D solid"), ("place_route", "Place & route")]),
          ("=  transactional invariants", [("erp_ledger", "ERP"), ("scada_dcs", "SCADA/DCS"), ("mes_exec", "MES"), ("plm_bom", "PLM")])]

INK, INK2, MUTED, HAIR, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
CAT = {"fable": "#2a78d6", "sonnet": "#eb6834", "haiku": "#1baf7a"}
avail = {f.name for f in font_manager.fontManager.ttflist}
FONT = next(c for c in ("Helvetica", "Arial", "Liberation Sans", "Nimbus Sans", "DejaVu Sans") if c in avail)
plt.rcParams.update({"font.family": [FONT, "DejaVu Sans"], "pdf.fonttype": 42})

# ---- data (a) ----
tmp = os.path.join(tempfile.mkdtemp(), "m.csv")
subprocess.run(["python3", f"{ROOT}/harness/build_matrix.py", "--models", ",".join(m for m, _ in MODELS),
                "--out", tmp], check=True, cwd=ROOT)
M = {r["task"]: r for r in csv.DictReader(open(tmp))}

def parse(cell):
    m = re.match(r"(PASS|FAIL) (\d+)/(\d+)", cell or "")
    return (m.group(1) == "PASS", int(m.group(2)), int(m.group(3))) if m else None

def fill(ok, frac):
    return RAMP[4] if ok else RAMP[min(3, int(frac * 4))]

def lum(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

# ---- data (b) ----
s = open(f"{ROOT}/results/ReviveBench_技术报告.html", encoding="utf-8").read()
i = s.find('<script id="R" type="application/json">'); j = s.find("</script>", i)
R = json.loads(s[i + len('<script id="R" type="application/json">'):j])
sim = R["contamination"]["similarity"]
# Cohort pass rates, recomputed from results/summary.json with contamination/analyze.py's filters
# (drop no-agent baselines, runs interrupted without passing, and runs with max_turns < 80).
# Model names are normalised to the underlying model (verified from trajectory init events):
# "sonnet5" (Bedrock re-runs) is claude-sonnet-5 like "sonnet"; "haiku4.5" is claude-haiku-4-5 like "haiku".
NORM = {"sonnet5": "sonnet", "haiku4.5": "haiku", "fable5.1": "fable"}
def compute_cohorts():
    from collections import defaultdict
    coh = defaultdict(lambda: [0, 0])
    for d in json.load(open(f"{ROOT}/results/summary.json")):
        if d["condition"] == "noagent" or (d.get("interrupted") and not d["post_pass"]) or d.get("max_turns", 0) < 80:
            continue
        t = json.load(open(f"{ROOT}/tasks/{d['task']}/task.json"))
        c = t.get("cohort", "obfuscated" if "obf" in d["task"] else "pre-cutoff")
        if c == "industrial":
            continue
        m = NORM.get(d["model"], d["model"])
        coh[f"{c}|{m}"][0] += bool(d["post_pass"]); coh[f"{c}|{m}"][1] += 1
    return {k: v for k, v in coh.items()}
cohorts = compute_cohorts()

fig = plt.figure(figsize=(11, 5.0), dpi=200)

# ================= (a) matrix =================
nm = len(MODELS); nrows = sum(len(g[1]) for g in GROUPS)
ax = fig.add_axes([0.005, 0.02, 0.60, 0.9])
LABW, CW, RH, GH = 13.5, 5.6, 2.3, 2.0
H_TOT = nrows * RH + len(GROUPS) * GH + RH + 4.0
ax.set_xlim(0, LABW + nm * CW + 0.5); ax.set_ylim(0, H_TOT); ax.axis("off")
top = H_TOT - 4.0
x0 = LABW
for vname, n in VENDORS:
    ax.text(x0 + n * CW / 2, top + 2.6, vname, fontsize=7.6, color=INK2, ha="center", va="center")
    ax.plot([x0 + 0.4, x0 + n * CW - 0.4], [top + 1.9, top + 1.9], color=BASE, lw=0.8)
    x0 += n * CW
for k, (_, label) in enumerate(MODELS):
    ax.text(LABW + k * CW + CW / 2, top + 0.8, label, fontsize=7.4, color=INK, ha="center", va="center", fontweight="bold")
y = top; passes = [0] * nm
for gname, rows in GROUPS:
    y -= GH
    ax.text(0.2, y + GH * 0.45, gname, fontsize=7.2, color=INK2, va="center")
    for task, label in rows:
        y -= RH
        ax.text(0.8, y + RH / 2, label, fontsize=7.6, color=INK, va="center")
        for k, (model, _) in enumerate(MODELS):
            p = parse(M[task].get(model)); cx = LABW + k * CW
            if p is None:
                ax.add_patch(FancyBboxPatch((cx + 0.15, y + 0.15), CW - 0.3, RH - 0.3,
                             boxstyle="round,pad=0,rounding_size=0.35", fc="#f3f2ee", ec="none"))
                ax.text(cx + CW / 2, y + RH / 2, "—", fontsize=7, color=MUTED, ha="center", va="center")
                continue
            ok, a, b = p; passes[k] += ok
            fc = fill(ok, a / b)
            ax.add_patch(FancyBboxPatch((cx + 0.15, y + 0.15), CW - 0.3, RH - 0.3,
                         boxstyle="round,pad=0,rounding_size=0.35", fc=fc, ec="none"))
            ax.text(cx + CW / 2, y + RH / 2, ("✓ " if ok else "") + f"{a}/{b}", fontsize=6.9,
                    color="white" if lum(fc) < 0.3 else INK, ha="center", va="center")
y -= RH * 1.1
ax.plot([LABW, LABW + nm * CW], [y + RH * 1.05, y + RH * 1.05], color=BASE, lw=0.8)
ax.text(0.8, y + RH / 2, "Engines passed", fontsize=7.8, color=INK, va="center", fontweight="bold")
for k in range(nm):
    ax.text(LABW + k * CW + CW / 2, y + RH / 2, f"{passes[k]}/13", fontsize=7.8, color=INK, ha="center",
            va="center", fontweight="bold")
fig.text(0.012, 0.955, "(a) Clean-room reconstruction of 13 industrial engines", fontsize=10, color=INK, fontweight="bold")
fig.text(0.012, 0.915, "hidden-verifier score of the best protocol run · dark + ✓ = pass · lighter = fail, shaded by "
         "within-row fraction", fontsize=7.0, color=INK2)

# ================= (b) revival: cohorts =================
fig.text(0.665, 0.955, "(b) Software revival: contamination controls", fontsize=10, color=INK, fontweight="bold")
for k, (m, col) in enumerate(CAT.items()):
    fig.lines.append(plt.Line2D([0.673 + k * 0.075], [0.912], marker="o", ms=5.5, lw=0, color=col, mec="white",
                                transform=fig.transFigure, figure=fig))
    fig.text(0.681 + k * 0.075, 0.912, m, fontsize=7.4, color=INK, va="center")

bx = fig.add_axes([0.695, 0.58, 0.28, 0.25])
coh = [("pre-cutoff", "pre-cutoff"), ("obfuscated", "obfuscated"), ("post-cutoff-2026", "post-cutoff")]
offs = {"fable": -0.26, "sonnet": 0.0, "haiku": 0.26}
for m, col in CAT.items():
    for xi, (key, _) in enumerate(coh):
        a, n = cohorts[f"{key}|{m}"]
        bx.plot([xi + offs[m]], [a / n], "o", ms=6.5, color=col, mec="white", mew=1.4, zorder=3)
        bx.text(xi + offs[m], a / n - 0.12, f"{a}/{n}", fontsize=6.2, color=INK2, ha="center", va="top")
bx.set_xticks(range(3)); bx.set_xticklabels([c[1] for c in coh], fontsize=7.4, color=INK)
bx.set_ylim(0, 1.12); bx.set_yticks([0, 0.5, 1]); bx.set_yticklabels(["0", "50%", "100%"], fontsize=6.8, color=MUTED)
bx.set_xlim(-0.6, 2.6)
for sp in ("top", "right", "left"): bx.spines[sp].set_visible(False)
bx.spines["bottom"].set_color(BASE); bx.tick_params(length=0)
bx.grid(axis="y", color=HAIR, lw=0.6, zorder=0)
bx.set_title("pass rate by cohort (runs passed / runs)", fontsize=7.4, color=INK2, loc="left", pad=6)

# ================= (b) revival: similarity =================
sx = fig.add_axes([0.695, 0.1, 0.28, 0.33])
rows = [("fable", 2.0), ("sonnet", 1.0), ("haiku", 0.0)]
DY = 0.2
for m, yv in rows:
    col = CAT[m]
    for task, dy, tag in (("deepimpute_reconstruct", DY, "original"), ("deepimpute_reconstruct_obf", -DY, "obfuscated")):
        for x in sim:
            if x["task"] != task or f"__{m}__" not in x["run"]:
                continue
            sx.plot([x["seqratio"]], [yv + dy], "o", ms=6, zorder=3,
                    color=col if x["pass"] else "white", mec="white" if x["pass"] else col,
                    mew=1.2 if x["pass"] else 1.4)
        sx.text(-0.015, yv + dy, tag, fontsize=6.4, color=MUTED, ha="right", va="center")
    sx.text(-0.2, yv, m, fontsize=7.4, color=INK, ha="right", va="center")
sx.set_xlim(0, 1.0); sx.set_ylim(-0.55, 2.55)
sx.set_xticks([0, 0.25, 0.5, 0.75, 1.0]); sx.set_xticklabels(["0", ".25", ".50", ".75", "1"], fontsize=6.8, color=MUTED)
sx.set_yticks([])
for sp in ("top", "right", "left"): sx.spines[sp].set_visible(False)
sx.spines["bottom"].set_color(BASE); sx.tick_params(length=0)
sx.grid(axis="x", color=HAIR, lw=0.6, zorder=0)
for yl in (0.5, 1.5):
    sx.axhline(yl, color=HAIR, lw=0.6, zorder=0)
sx.set_xlabel("line similarity of the reconstructed module to the original", fontsize=7.2, color=INK2, labelpad=3)
sx.set_title("reconstruction similarity per run · hollow = run failed", fontsize=7.4, color=INK2, loc="left", pad=6)

out = f"{ROOT}/paper/figures/fig2_results" + ("_glm" if "--with-glm" in sys.argv else "") + ("_kimi" if "--with-kimi" in sys.argv else "")
fig.savefig(out + ".pdf", facecolor="white")
fig.savefig(out + ".png", dpi=200, facecolor="white")
print("passes per model:", dict(zip([m for m, _ in MODELS], passes)), "->", out)
