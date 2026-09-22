#!/usr/bin/env python3
"""Render results/summary.json (+ oracle references) into results/report.html."""
import os
import pathlib
import json, pathlib, collections, html, datetime
ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
rows = json.loads((ROOT / "results" / "summary.json").read_text())
tasks = {}
for t in sorted((ROOT / "tasks").glob("*/task.json")):
    d = json.loads(t.read_text()); tasks[d["id"]] = d
ORDER = ["deepimpute_keras3", "dca_keras3", "deepimpute_reconstruct", "deepimpute_reconstruct_obf", "caduceus_modern", "pymol_modern", "qupath_modern"]
IND = ["stats_nist", "spice_ngspice", "plc_iec61131", "fem_nafems", "cad2d_dxf"]
NICE = {"stats_nist": "Statistics engine (SAS / SPSS)", "spice_ngspice": "Circuit simulation (HSPICE / Spectre)", "plc_iec61131": "PLC runtime (TIA Portal / Studio 5000)", "fem_nafems": "Finite elements (Nastran / ABAQUS)", "cad2d_dxf": "2D CAD kernel (AutoCAD)", "deepimpute_reconstruct_obf": "DeepImpute reconstruction (obfuscated)", "deepimpute_keras3": "DeepImpute → Keras 3", "dca_keras3": "DCA → Keras 3", "deepimpute_reconstruct": "DeepImpute core module reconstruction",
        "caduceus_modern": "Caduceus -> torch 2.x / mamba kernels", "pymol_modern": "PyMOL 2.3 → Python 3.12", "qupath_modern": "QuPath 0.2.3 → JDK 21"}
ROT = {"stats_nist": "No source to start from: a subset of the SPSS syntax is specified, and NIST certified accuracy is required (including a degree-10 ill-conditioned polynomial and nonlinear fits from hard starting points)",
       "spice_ngspice": "Only the netlist syntax and the analysis types are specified; modified nodal analysis, Newton-Raphson, implicit integration and diode / MOS level-1 models must all be built",
       "plc_iec61131": "Only a subset of IEC 61131-3 structured text and the scan-cycle semantics are given; the compiler and a deterministic runtime must be built",
       "fem_nafems": "Only a subset of the ABAQUS input deck is given; CPS8/CPE8 isoparametric elements, sparse assembly and a generalised eigensolver must be built",
       "cad2d_dxf": "Only DXF and the geometric operations are specified; polyline boolean / offset / fillet with arcs, and DXF read-write, must be built",
       "deepimpute_reconstruct_obf": "As T3, but package, class, function, argument and file names are systematically renamed (`gapfill.subnet.SubnetImputer` and so on) and the paper / GitHub references removed, to rule out verbatim recall", "deepimpute_keras3": "Keras 3 / NumPy 2 / pandas 2 break 2022-era code (`lr=`, `groupby(axis=1)`, a custom loss through `to_json`)",
       "dca_keras3": "Depends on private APIs that no longer exist: `keras.engine.topology`, `keras.objectives`, tf1 sessions; plus major scanpy/anndata versions",
       "deepimpute_reconstruct": "`multinet.py` (the 379-line core) is deleted; only the callers, tests, README and paper remain",
       "caduceus_modern": "The mamba-ssm 1.2 kernels do not match torch 2.x / CUDA 12.x and must be rebuilt; the transformers 5 remote-code API has changed",
       "pymol_modern": "Python 3.12 removed distutils and `open(..,'rU')`; the NumPy 2 C API; 2019-era system libraries (glew/glm/msgpack/mmtf)",
       "qupath_modern": "Gradle 6.5, JDK 14 jpackage and JavaFX 14 all fail under JDK 21, and only JDK 21 is allowed"}
VERIFY = {"stats_nist": "43 certified NIST StRD datasets, log relative error thresholds graded by difficulty; SciPy / statsmodels forbidden",
          "spice_ngspice": "10 hidden netlists against ngspice waveforms (RMS <= 2%, peak <= 5%); any existing simulator forbidden",
          "plc_iec61131": "10 hidden programs with stimulus sequences; the output trace is compared scan by scan with a reference interpreter",
          "fem_nafems": "4 benchmarks against CalculiX displacement fields (<=1%) and closed-form solutions (Timoshenko / Lame / Kirsch); SciPy and any FE library forbidden",
          "cad2d_dxf": "31 hidden operations against ezdxf + shapely quantities (area / perimeter / centroid / boolean); ezdxf and shapely forbidden",
          "deepimpute_reconstruct_obf": "The same verifier as T3 with identifiers renamed to match; calibrated on the oracle", "deepimpute_keras3": "Version floors (anti-downgrade), imports, masked-recovery r and residual r (calibrated on the oracle), the CLI end to end, and 4 upstream test files",
          "dca_keras3": "As on the left, plus 9 autoencoder types that must train, latent / return_info outputs, and a CLI that writes mean.tsv",
          "deepimpute_reconstruct": "As T1, but run in the software's native environment (TF 2.10), so only the fidelity of the reconstruction is measured",
          "caduceus_modern": "GPU available, kernels and package import, RC equivariance of the pretrained model (relative error <1e-3), masked-LM accuracy above a randomly initialised model, and 430 upstream tests",
          "pymol_modern": "Python>=3.12 / NumPy>=2, no prebuilt pymol package, atom counts / distances / DSS / RMSD / FASTA matching the oracle, a ray-traced PNG, and `pymol -cq`",
          "qupath_modern": "Class bytecode >= Java 17, run_qupath.sh pointing at the self-built artefact, and a headless cell count under xvfb within 2% of the official 0.2.3"}

ORDER += sorted(t for t in tasks if t not in ORDER and t.endswith("_reconstruct2026"))
for t in tasks:
    NICE.setdefault(t, t.replace("_reconstruct2026", " reconstruction (2026 package)"))

def fmt(x, nd=2):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))

agent_rows = [r for r in rows if r["condition"] != "noagent"]
per_task = collections.OrderedDict()
for t in ORDER + IND:
    rs = [r for r in agent_rows if r["task"] == t]
    # a pass is a pass even if the agent was cut off afterwards; an interrupted failure is inconclusive and excluded
    full = [r for r in rs if r.get("max_turns", 0) >= 80 and (r["post_pass"] or not r.get("interrupted"))]
    per_task[t] = {"n": len(full), "pass": sum(1 for r in full if r["post_pass"]),
                   "all_n": len(rs), "all_pass": sum(1 for r in rs if r["post_pass"]),
                   "cost": [r["cost_usd"] for r in full if r.get("cost_usd")],
                   "turns": [r["num_turns"] for r in full if r.get("num_turns")],
                   "baseline": any(r.get("baseline_pass") for r in rows if r["task"] == t)}

def esc(s): return html.escape(str(s))

# ---- summary strip + bar chart (single series: restore rate per task) ----
strip = []
bars = []
W, BH, GAP, LW = 720, 26, 10, 250
for i, t in enumerate(ORDER):
    p = per_task[t]; rate = (p["pass"] / p["n"]) if p["n"] else 0
    y = i * (BH + GAP)
    bw = max(4, int((W - LW - 60) * rate))
    bars.append(f'<text x="{LW-10}" y="{y+BH*0.68}" text-anchor="end" class="lbl">{esc(NICE[t])}</text>'
                f'<rect x="{LW}" y="{y}" width="{W-LW-60}" height="{BH}" class="track"/>'
                f'<rect x="{LW}" y="{y}" width="{bw}" height="{BH}" rx="3" class="bar"><title>{esc(NICE[t])}: {p["pass"]}/{p["n"]} full-budget runs passed</title></rect>'
                f'<text x="{LW+bw+8}" y="{y+BH*0.68}" class="val">{p["pass"]}/{p["n"]}</text>')
    strip.append(f'''<div class="tile"><div class="eyebrow">{esc(tasks[t]["tier"])}</div><div class="tname">{esc(NICE[t])}</div>
      <div class="big">{p["pass"]}<span class="of">/{p["n"]}</span></div>
      <div class="sub">full-budget runs passed · baseline {"pass" if p["baseline"] else "fail"} · median cost ${fmt(sorted(p["cost"])[len(p["cost"])//2] if p["cost"] else None)}</div></div>''')
chart_h = len(ORDER) * (BH + GAP)
chart = f'<svg viewBox="0 0 {W} {chart_h}" class="chart" role="img" aria-label="restore rate by task">{"".join(bars)}</svg>'

ibars = []
for i, t in enumerate(IND):
    p = per_task[t]; rate = (p["pass"] / p["n"]) if p["n"] else 0
    y = i * (BH + GAP); bw = max(4, int((W - LW - 60) * rate))
    ibars.append(f'<text x="{LW-10}" y="{y+BH*0.68}" text-anchor="end" class="lbl">{esc(NICE[t])}</text>'
                 f'<rect x="{LW}" y="{y}" width="{W-LW-60}" height="{BH}" class="track"/>'
                 f'<rect x="{LW}" y="{y}" width="{bw}" height="{BH}" rx="3" class="bar"><title>{esc(NICE[t])}: {p["pass"]}/{p["n"]}</title></rect>'
                 f'<text x="{LW+bw+8}" y="{y+BH*0.68}" class="val">{p["pass"]}/{p["n"]}</text>')
ichart = f'<svg viewBox="0 0 {W} {len(IND)*(BH+GAP)}" class="chart" role="img" aria-label="industrial engine build rate">{"".join(ibars)}</svg>'
ind_cards = "".join(f'''<tr><td><strong>{esc(NICE[t])}</strong><div class="muted small">{esc(tasks[t]["tier"])}</div></td>
<td>{ROT[t]}</td><td>{VERIFY[t]}</td></tr>''' for t in IND)

# ---- run table ----
trs = []
for r in sorted(rows, key=lambda r: (ORDER.index(r["task"]) if r["task"] in ORDER else 99, r["condition"], r["model"], r["run_id"])):
    diff = r.get("diff", {}) or {}
    failed = [k for k, v in r.get("post_checks", {}).items() if not v]
    status = '<span class="pill ok">✓ restored</span>' if r.get("post_pass") else ('<span class="pill base">baseline</span>' if r["condition"] == "noagent" else '<span class="pill bad">✗ not restored</span>')
    flags = []
    if r.get("interrupted"): flags.append('<span class="flag">interrupted (network / rate limit)</span>')
    if r.get("leak_audit"): flags.append('<span class="flag warn">read the run directory</span>')
    if diff.get("visible_tests_modified"): flags.append('<span class="flag">modified upstream tests</span>')
    if diff.get("tests_added"): flags.append('<span class="flag ok">+regression tests</span>')
    trs.append("<tr>" + "".join(f"<td>{c}</td>" for c in [
        esc(NICE.get(r["task"], r["task"])), esc(r["condition"]), esc(r["model"]) + (f' <span class="mono muted">@{r["max_turns"]}</span>' if r["condition"] != "noagent" and r.get("max_turns") != 80 and r.get("max_turns") else ""),
        esc(r["run_id"]), status, fmt(r.get("num_turns")), fmt(r.get("n_tool_calls")), fmt(r.get("cost_usd")),
        fmt(r["agent_wall_s"] / 60, 1) if r.get("agent_wall_s") else "-",
        f'{diff.get("code_files", diff.get("n_files","-"))} / +{diff.get("code_added", diff.get("lines_added","-"))} −{diff.get("code_deleted", diff.get("lines_deleted","-"))}' if diff else "-",
        " ".join(flags) or "-", esc(", ".join(failed)) if failed and r["condition"] != "noagent" else "-"]) + "</tr>")

for t in ORDER + IND:
    ROT.setdefault(t, tasks[t].get("description", ""))
    VERIFY.setdefault(t, f"hidden upstream test suite ({tasks[t].get('oracle_passed', '?')} passing in a fresh env) · install · target module imports")
task_cards = "".join(f'''<tr><td><strong>{esc(NICE[t])}</strong><div class="muted small">{esc(tasks[t]["tier"])} · env <span class="mono">{esc(tasks[t]["env"])}</span></div></td>
<td>{ROT[t]}</td><td>{VERIFY[t]}</td></tr>''' for t in ORDER)

# ---- contamination analysis (contamination/analyze.py) ----
try:
    CA = json.loads((ROOT / "contamination" / "analysis.json").read_text())
except Exception:
    CA = {"similarity": [], "cohorts": {}}
def _sim_row(r):
    pill = '<span class="pill ok">✓</span>' if r["pass"] else '<span class="pill bad">✗</span>'
    return ("<tr><td>%s</td><td class=\"mono\">%s</td><td>%s</td><td>%.2f</td><td>%.2f</td><td>%d</td></tr>"
            % (esc(NICE.get(r["task"], r["task"])), esc(r["run"]), pill, r["seqratio"], r["exact"], r["lines"]))
sim_rows = "".join(_sim_row(r) for r in CA["similarity"])
coh_rows = "".join("<tr><td>%s</td><td>%s</td><td>%d/%d</td></tr>" % (esc(k.split("|")[0]), esc(k.split("|")[1]), v[0], v[1]) for k, v in sorted(CA["cohorts"].items()))
MTASKS = ["stats_nist", "spice_ngspice", "plc_iec61131", "fem_nafems", "cad2d_dxf"]
MMODELS = ["fable5.1", "opus5", "sonnet5", "haiku4.5"]
MNAME = {"fable5.1": "fable 5.1", "opus5": "opus 5", "sonnet5": "sonnet 5", "haiku4.5": "haiku 4.5"}
mcell = {}
for d in rows:
    if d.get("run_id", "").startswith("m") and d["condition"] == "protocol" and d["model"] in MMODELS:
        mm = d.get("post_metrics", {})
        sc = f"{mm.get('n_pass','?')}/{mm.get('n_total','?')}"
        prev = mcell.get((d["task"], d["model"]))
        if prev is None or (d["post_pass"] and not prev[0]):
            mcell[(d["task"], d["model"])] = (d["post_pass"], d.get("num_turns"), d.get("cost_usd") or 0, sc)
mrows = []
for t in MTASKS:
    tds = []
    for mo in MMODELS:
        c = mcell.get((t, mo))
        if not c:
            tds.append('<td class="muted">-</td>'); continue
        ok, turns, cost, sc = c
        pill = '<span class="pill ok">pass</span>' if ok else '<span class="pill bad">fail</span>'
        tds.append(f'<td>{pill}<div class="mono muted small">{turns} turns · ${cost:.2f} · {sc}</div></td>')
    mrows.append(f'<tr><td><strong>{esc(NICE.get(t, t))}</strong></td>' + "".join(tds) + '</tr>')
mgrid = ('<div class="tablewrap"><table><thead><tr><th>Engine</th>' +
         "".join(f'<th>{MNAME[m]}</th>' for m in MMODELS) +
         '</tr></thead><tbody>' + "".join(mrows) + '</tbody></table></div>')
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
total_cost = sum(r.get("cost_usd") or 0 for r in rows)
n_agent = len(agent_rows)
page = f'''<title>ReviveBench</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--bg:#F4F6F4;--panel:#FFFFFF;--ink:#17231F;--ink2:#4A5A54;--muted:#7B8A84;--line:#D9E0DC;--accent:#1F7A5C;--accent-ink:#155A44;--bad:#B5442D;--warn:#9A6B12;--track:#E3E9E6;--flag:#EEF2F0}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#111815;--panel:#18211D;--ink:#E6EDE9;--ink2:#B4C1BA;--muted:#7F8E87;--line:#2A3630;--accent:#4FB58F;--accent-ink:#7ED3B3;--bad:#E07A62;--warn:#D9A441;--track:#243029;--flag:#1F2A25}}}}
:root[data-theme="dark"]{{--bg:#111815;--panel:#18211D;--ink:#E6EDE9;--ink2:#B4C1BA;--muted:#7F8E87;--line:#2A3630;--accent:#4FB58F;--accent-ink:#7ED3B3;--bad:#E07A62;--warn:#D9A441;--track:#243029;--flag:#1F2A25}}
body{{background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15px;line-height:1.6;margin:0}}
main{{max-width:1080px;margin:0 auto;padding:40px 28px 80px}}
h1{{font-family:Newsreader,Georgia,serif;font-weight:600;font-size:44px;line-height:1.1;margin:0 0 6px;text-wrap:balance}}
h2{{font-family:Newsreader,Georgia,serif;font-weight:600;font-size:26px;margin:44px 0 12px;text-wrap:balance}}
h3{{font-size:16px;font-weight:600;margin:22px 0 6px}}
p,li{{max-width:72ch}} .lede{{font-size:18px;color:var(--ink2);max-width:70ch}}
.eyebrow{{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:600}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:22px 0}}
.tile{{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px 16px}}
.tname{{font-weight:600;margin:4px 0 2px;font-size:14px}} .big{{font-family:Newsreader,serif;font-size:36px;line-height:1.1;color:var(--accent-ink);font-variant-numeric:tabular-nums}}
.of{{font-size:20px;color:var(--muted)}} .sub{{font-size:12px;color:var(--muted);margin-top:4px}}
.chart{{width:100%;height:auto;max-width:760px;display:block;margin:10px 0 4px}} .chart .lbl{{font:13px "IBM Plex Sans",sans-serif;fill:var(--ink2)}}
.chart .val{{font:13px "IBM Plex Mono",monospace;fill:var(--ink)}} .chart .track{{fill:var(--track)}} .chart .bar{{fill:var(--accent)}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--panel)}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}} th,td{{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}}
th{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);white-space:nowrap}} tr:last-child td{{border-bottom:0}}
td:nth-child(n+6){{font-variant-numeric:tabular-nums;white-space:nowrap}}
.pill{{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}}
.pill.ok{{background:color-mix(in srgb,var(--accent) 16%,transparent);color:var(--accent-ink)}} .pill.bad{{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad)}}
.pill.base{{background:var(--flag);color:var(--muted)}}
.flag{{display:inline-block;font-size:11px;padding:0 6px;border-radius:4px;background:var(--flag);color:var(--ink2);margin-right:3px;white-space:nowrap}}
.flag.warn{{color:var(--warn)}} .flag.ok{{color:var(--accent-ink)}}
.mono{{font-family:"IBM Plex Mono",monospace;font-size:12.5px}} .muted{{color:var(--muted)}} .small{{font-size:12px}}
code{{font-family:"IBM Plex Mono",monospace;font-size:12.5px;background:var(--flag);padding:0 4px;border-radius:3px}}
.callout{{border-left:3px solid var(--accent);padding:6px 14px;background:var(--panel);margin:14px 0;max-width:76ch}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}
.foot{{color:var(--muted);font-size:12px;margin-top:40px;border-top:1px solid var(--line);padding-top:12px}}
</style>
<main>
<div class="eyebrow">Pilot report · {now} · {n_agent} agent runs · ${total_cost:.0f} total</div>
<h1>ReviveBench: coding agents reviving dead scientific software</h1>
<p class="lede">Two families of experiments. <strong>One</strong>: give an agent a scientific software repository that no longer runs (rotted dependencies, a deleted core module, an obsolete toolchain) and ask whether it can restore the software to a working state that <strong>passes a hidden verifier</strong>. <strong>Two</strong>: give it no source at all, only an open standard, and ask whether it can build the core engine of industrial software from nothing (statistics, circuit simulation, PLC, finite elements, 2D CAD). The verifiers are invisible to the agent, their numerical thresholds are calibrated in the software's native environment (the oracle), and they include anti-downgrade, anti-prebuilt and anti-test-editing checks.</p>
<p class="muted small">This is the pilot report. It predates the GLM column and the re-runs, so a few figures here are superseded by the tables in the paper.</p>

<div class="tiles">{"".join(strip)}</div>
<h2>Part one: restoring dead scientific software</h2>
<h3 style="font-size:15px;font-weight:600;margin:14px 0 4px">Restore rate by task (full-budget runs; runs cut off by a quota limit that had not passed are excluded)</h3>
{chart}
<p class="muted small">Bar = runs passing the hidden verifier / full-budget runs. The no-agent baseline fails on every task, so the software really is broken.</p>

<h2>Tasks and verifiers</h2>
<div class="tablewrap"><table><thead><tr><th>Task</th><th>How it is broken</th><th>What the hidden verifier checks</th></tr></thead><tbody>{task_cards}</tbody></table></div>

<h2>Main findings</h2>
<ol>
<li><strong>Dependency rot (T1) is saturated for current agents.</strong> On DeepImpute under Keras 3 / NumPy 2, fable, sonnet and haiku all pass on the first attempt, the cheapest (haiku) for $0.54; the masked-recovery r matches the oracle digit for digit (sonnet's 0.901 / 0.297 are identical to the oracle). The only failure is an ablation whose budget was cut to 12 turns, which puts the lower bound of difficulty in turns rather than capability.</li>
<li><strong>Reconstruction (T3) is faithful too.</strong> From the paper, the callers and the tests alone, four runs (fable x3, sonnet x1) rewrote `multinet.py` and all passed the upstream tests and the functional checks, with masked-recovery r of 0.894-0.902 against the oracle's 0.901 and residual correlation 0.26-0.29 against 0.30: what came back is the same method, not a substitute that merely works.</li>
<li><strong>Harder tasks need more turns and larger patches, but remain solvable.</strong> DCA (every private Keras API gone) passes under the protocol condition after 62 turns and $9.5, changing 13 files (+410/-132), including 9 autoencoder types and the CLI. Caduceus compiles the mamba kernels from source in 15 turns in a clean environment and makes the pretrained model satisfy RC equivariance exactly (relative error 0.0, masked-LM accuracy 0.75 against 0.0 for a random initialisation). QuPath 0.2.3 rebuilds under JDK 21 with Gradle 8 (3/3 runs, &lt;=30 turns, about $3.7) and its headless cell detection finds 3842 cells with nucleus area and OD means identical to the official release. PyMOL 2.3 is the hardest: built from C++ source under Python 3.12 / NumPy 2 (distutils and <code>'rU'</code> gone, the NumPy 2 C API, 2019-era system libraries such as glew/glm/msgpack/mmtf supplied through mamba), passing after 112 turns and $11.4 (default) and 117 turns and $15.2 (protocol): atom counts, CA distances, DSS, RMSD and FASTA all match the oracle, and both the ray-traced PNG and <code>pymol -cq</code> work. Two attempts cut off by rate limiting never finished the build.</li>
<li><strong>The verifiers are the most error-prone part of the project.</strong> The pilot found and fixed four verifier defects: the upstream tests ran against the original snapshot rather than the repaired code (`python -m pytest` puts cwd first on sys.path); the upstream tests depended on each other's order (TF thread-pool initialisation); some upstream tests were already broken in the software's native environment (DCA `zinb-elempi`, Caduceus `test_rcps_add_norm_wrapper`); and the agent could `cd ..` and read the baseline verification output. The conclusion: every task's verifier must first be run in the oracle environment, and hidden assets must live outside the agent's working tree.</li>
<li><strong>The test-editing flag works.</strong> Every run that touched an upstream test was flagged, and manual review found two kinds: reasonable adaptations for Keras 3, and fixes to tests that were themselves buggy upstream (Caduceus). No run deleted a test or weakened an assertion.</li>
<li><strong>Contamination control changed how the results may be stated.</strong> In the original reconstruction task, sonnet's code is 96.7% line-identical to the original, so that task is contaminated by memorisation; the obfuscated variant and the 2026-package control show fable's restore rate unchanged (next section).</li>
<li><strong>Infrastructure is the main source of noise.</strong> A cluster DNS outage and a session usage limit each cut off five parallel runs (flagged as interrupted and re-run; the three QuPath runs had already finished their builds and passed); and replacing torch in a base environment mid-run contaminated Caduceus s1 (s2 is the clean control). Runs must be fully isolated (a fresh venv or conda clone each), and base environments frozen for the duration.</li>
</ol>

<h2>Part two: clean-room reconstruction of industrial software</h2>
<p>Cloning a closed product such as AutoCAD, ANSYS or SAP wholesale is neither feasible nor legally sound. What is feasible is a <strong>clean-room rebuild of the core engine</strong>: an open standard as the specification (NIST certified values, SPICE netlists, IEC 61131-3, ABAQUS input decks, DXF), an open-source counterpart as the oracle (ngspice, CalculiX, a reference interpreter, ezdxf + shapely), and "is the engine correct" becomes a deterministic score. The agent receives only a specification and three worked examples, and may not install any existing implementation -- the verifier checks the environment.</p>
{ichart}
<div class="tablewrap"><table><thead><tr><th>Engine</th><th>Starting point and difficulty</th><th>Hidden verifier</th></tr></thead><tbody>{ind_cards}</tbody></table></div>
<div class="callout"><strong>Result.</strong> All five engines were built: the statistics engine meets the thresholds on 43 certified NIST problems, the SPICE engine agrees with ngspice to 0.006-0.15% RMS, the PLC traces match the reference interpreter scan for scan, the finite-element solver is within 0.71 um of CalculiX at the worst node, and the 2D CAD kernel gets 29/31 operations right. Costs run from $1.7 to $13. Model differences are sharpest here: on the CAD geometry kernel sonnet failed all six attempts (twice by installing ezdxf in violation of the rules, otherwise on arc-direction conventions) while fable passed both of its (22 and 37 turns, about 2,500 lines written from scratch); conversely fable wrote working 1,600-2,400 line engines for SPICE and PLC in 7-8 turns, about ten times sonnet's turn efficiency. A domain skill pack generated by LabAgent gave no benefit (2/5) and on CAD actively induced a violation by recommending ezdxf.</div>

<h2>Model matrix: five engines x four models under one set of verifiers</h2>
<p>All runs go through the Bedrock proxy, protocol condition, the same hidden verifiers. The score is the number of hidden cases passed.</p>
{mgrid}
<div class="callout"><strong>How to read it.</strong> Turn efficiency differs by an order of magnitude: fable 5.1 averages 27.5 turns, opus 5 averages 101.6 and hits the cap in three of five runs. Opus is the only model to pass all five, at $61.41; sonnet 5 takes four for $20 and is the best value, with the only perfect score on PLC. Sonnet solved 2D CAD for the first time after six failures, the only change being a turn cap raised to 120 -- it sits at the edge of its capability on that task, and turns rather than capability are the deciding variable. Haiku 4.5 fails all five, but gives a clear failure signal for about $1 each time, which makes it a cheap probe for task difficulty.</div>

<h2>Capability or contamination?</h2>
<p>All of this software predates the models' knowledge cutoff (2026-06), so both the fixes and the sources may have been memorised. Three controls:</p>
<ol>
<li><strong>Verbatim recall probe</strong>: asked to write out <code>multinet.py</code> from memory with no tools, all three models declined (3-12 lines of output), so the probe cannot by itself prove the absence of memorisation.</li>
<li><strong>Reconstruction similarity</strong>: compare the rebuilt module with the original line by line after normalisation. On the original task, sonnet's reconstruction is <strong>96.7% line-identical</strong> to the original, down to internal variable names and print strings, which can only be memorisation; fable is at 51-79%.</li>
<li><strong>Obfuscated task</strong>: package, class, function, argument and file names are systematically renamed and the paper references removed, with the verifier renamed to match. If success depends on recall, the pass rate should drop; if it is capability, the pass rate holds while similarity falls.</li>
<li><strong>Post-cutoff control (2026 packages)</strong>: bioinformatics Python packages created after the knowledge cutoff, with their most-imported module deleted and their own test suite hidden and used for verification. They cannot have been memorised.</li>
</ol>
<div class="grid2">
<div><h3>Similarity between the rebuilt module and the original</h3><div class="tablewrap"><table><thead><tr><th>Task</th><th>Run</th><th>Pass</th><th>Sequence similarity</th><th>Line-identical</th><th>Lines</th></tr></thead><tbody>{sim_rows}</tbody></table></div>
<p class="muted small">Reconstructions of the obfuscated task are mapped back to the original names before comparison. Unrelated files sit at a baseline similarity of about 0.04.</p></div>
<div><h3>Restore rate by cohort</h3><div class="tablewrap"><table><thead><tr><th>Cohort</th><th>Model</th><th>Restored</th></tr></thead><tbody>{coh_rows}</tbody></table></div>
<p class="muted small">pre-cutoff = the six original tasks; obfuscated = the renamed DeepImpute; post-cutoff-2026 = the new 2026 packages. Only full-budget, uninterrupted runs count.</p></div>
</div>
<div class="callout"><strong>How to read it.</strong> Obfuscation drops similarity from 0.51-0.96 to 0.12-0.46 while the pass rate does not fall (fable 3/3, sonnet 2/2, haiku 1/1): a model recites when it can, which inflates similarity, and derives an equivalent implementation from the callers, the tests and the method description when it cannot. The 2026 packages (interelate, 133 tests; binderranker, 843; sirna-data-grabber, 240 -- all passing on the oracle, all failing at baseline once the module is deleted) are the cleanest evidence: fable 8/9 (its one failure fails 2 of 843 tests), sonnet 2/3, haiku 1/3. So <strong>fable's results on the original tasks are capability, not contamination</strong>, while weaker models fall further on tasks that cannot be recalled, which suggests their results on older tasks lean more on memory. New tasks should be drawn from repositories created after the cutoff, with an obfuscated control alongside.</div>
<p class="muted small">Incidental finding: a comparable project appeared on GitHub in 2026-07, <span class="mono">DoctorDean/lazarus</span> ("takes a dead research repo and turns it into a callable pipeline"), worth citing as related work.</p>

<h2>All runs</h2>
<div class="tablewrap"><table><thead><tr><th>Task</th><th>Condition</th><th>Model</th><th>id</th><th>Result</th><th>Turns</th><th>Tool calls</th><th>$</th><th>Minutes</th><th>Code patch files/+/-</th><th>Flags</th><th>Failed checks</th></tr></thead>
<tbody>{"".join(trs)}</tbody></table></div>
<p class="muted small">Conditions: <code>default</code> = a natural-language goal; <code>protocol</code> = a structured restoration protocol (inventory, reproduce, root-cause table, minimal faithful patch, verify, regression test, report); <code>noagent</code> = the verifier alone, to confirm the software is broken. @N marks a non-default turn budget. The patch size counts source and configuration files only, excluding test data, build products and documentation.</p>

<h2>Scaling up: from concept to project</h2>
<div class="grid2">
<div><h3>Generating tasks automatically</h3><p>"Time-travel rot" can be manufactured in bulk: take repositories on bioconda / PyPI / GitHub that have been unmaintained for two years or more and ship tests or examples, run their tests in a current environment, and every failure is a task; running them in their native environment gives the oracle. Functional checks are drafted by an LLM and reviewed by hand, about an hour of human work per task. T3 is generated by deleting the module with the highest centrality in the call graph; T5 pairs an old release with a modern toolchain.</p></div>
<div><h3>Evaluation</h3><p>The primary metric is restore rate (pass@1 / pass@k); secondary metrics are turns, cost, patch size, test-editing rate and access outside the workspace; each task ships an oracle reference value and the provenance of its threshold. Three ablation axes -- model, budget, protocol -- aim to find the cheapest model that solves each tier.</p></div>
<div><h3>Applications</h3><p>(a) A revive bot that opens PRs against unmaintained repositories with a root-cause table and regression tests; (b) reviving a lab's own old pipelines (our group's Delphi, gReLU and scGPT dependency problems are exactly this); (c) a bulk migration assistant for bioconda / Bioconductor maintainers; (d) an agent evaluation set -- SWE-bench for scientific software rot -- that connects to LabAgent's read-repo, write-skill, reproduce loop.</p></div>
<div><h3>Next</h3><p>(1) Bring every task to 5 seeds and 3 models; (2) add 10 more genuinely unmaintained repositories (scVI 0.x, scGen, an old MAGIC, SAVER-X, DNABERT 1, old scanpy tutorials); (3) turn the restoration protocol into a Claude Code skill and measure its benefit; (4) isolate the verifier and the agent under different UIDs or containers; (5) submit passing patches upstream as PRs and count how many are merged.</p></div>
</div>
<div class="foot">Repository: <span class="mono">{ROOT}</span> · regenerate with <span class="mono">python3 harness/aggregate.py &amp;&amp; python3 harness/report.py</span> · full trajectories in <span class="mono">runs/&lt;task&gt;/&lt;cond&gt;__&lt;model&gt;__&lt;id&gt;/trajectory.jsonl</span></div>
</main>
'''
(ROOT / "results" / "report.html").write_text(page)
print("report written", len(page))
