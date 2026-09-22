#!/usr/bin/env python3
"""Hidden verifier for synth_verilog.

Judgement is formal: a SAT-based equivalence checker proves the candidate's gate-level netlist
equivalent to the source RTL (complete proof for combinational designs, temporal induction with a
bounded fallback for sequential ones). Simulation is only a backstop, and area is informational.

usage: verify.py --workspace <ws> --out <report.json> [--synth-cmd "<cmd> {src} {out}"] [--skip-env-check]
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DESIGNS = HERE / "designs"

# Oracle tools live in the conda env. The OSS CAD Suite bundle was tried and rejected: it is built
# against glibc 2.35 while this cluster has 2.28, and putting its lib on LD_LIBRARY_PATH breaks every
# child process, not just yosys.
_CONDA = ROOT / "envs" / "eda_oracle"


def _tool(name):
    p = _CONDA / "bin" / name
    return p if p.exists() else pathlib.Path(shutil.which(name) or p)


YOSYS = _tool("yosys")
IVERILOG = _tool("iverilog")
VVP = _tool("vvp")

ALLOWED_CELLS = {"and", "or", "not", "nand", "nor", "xor", "xnor", "buf", "DFF"}
FORBIDDEN_KEYWORDS = ("always", "initial", "case", "casez", "casex", "if", "else", "for",
                      "while", "function", "task", "generate", "assign_op")
FORBIDDEN_PKGS = ("pyverilog", "hdlconvertor", "vcdvcd", "cocotb", "amaranth", "migen", "myhdl")


def sh(cmd, cwd=None, timeout=600, env=None):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout + "\n" + p.stderr)[-6000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def check_legality(netlist_text, top):
    """the netlist may only instantiate primitives / DFF, alias or tie wires"""
    t = strip_comments(netlist_text)
    problems = []
    body = t
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", body):
            problems.append(f"contains forbidden keyword {kw}")
    # Continuous assignments may only alias or tie signals: a bare signal, a bit/part select, a
    # constant, or a concatenation of those. Structural netlists legitimately wire up vectors with
    # concatenation, so rejecting that would fail correct work; operators stay banned either way.
    item = r"[\w$\\]+(?:\s*\[\s*\d+\s*(?::\s*\d+\s*)?\])?|\d+'[bdhBDH][0-9a-fA-FxzXZ_?]+|\d+"
    alias = re.compile(r"(?:%s)|\{\s*(?:%s)(?:\s*,\s*(?:%s))*\s*\}" % (item, item, item))
    for m in re.finditer(r"\bassign\b([^;]*);", body):
        rhs = m.group(1).split("=", 1)[-1].strip()
        if not alias.fullmatch(rhs):
            problems.append(f"assign right-hand side is neither an alias nor a constant: {rhs[:40]}")
    # instantiations: first token of any statement containing '(' must be an allowed cell
    decl_kw = {"module", "endmodule", "input", "output", "inout", "wire", "reg", "parameter",
               "localparam", "assign", "supply0", "supply1"}
    for m in re.finditer(r"(?m)^\s*([A-Za-z_]\w*)\s+(?:[A-Za-z_]\w*\s*)?\(", body):
        head = m.group(1)
        if head in decl_kw:
            continue
        if head not in ALLOWED_CELLS:
            problems.append(f"instantiates a disallowed cell {head}")
    n_cells = len(re.findall(r"(?m)^\s*(?:%s)\s+" % "|".join(sorted(ALLOWED_CELLS)), body))
    has_top = re.search(r"\bmodule\s+" + re.escape(top) + r"\b", body) is not None
    if not has_top:
        problems.append(f"missing top module {top}")
    return sorted(set(problems)), n_cells


def yosys_equiv(gold, netlist, cells, top, seq, tmp):
    """returns (proved, method, log_tail)"""
    def run(extra, tag):
        script = tmp / f"eq_{top}_{tag}.ys"
        script.write_text(f"""
read_verilog {gold}
hierarchy -top {top}
proc
opt_clean
design -stash gold
read_verilog {cells} {netlist}
hierarchy -top {top}
proc
flatten
opt_clean
design -stash gate
design -copy-from gold -as gold {top}
design -copy-from gate -as gate {top}
miter -equiv -flatten -make_assert gold gate miter
hierarchy -top miter
proc
opt -full
sat -verify -prove-asserts -set-init-zero {extra} miter
""")
        rc, out = sh([str(YOSYS), "-q", "-s", str(script)], timeout=1800)
        ok = rc == 0 and ("SUCCESS" in out or "Assert" not in out)
        return ok, out
    if not seq:
        ok, out = run("", "comb")
        return ok, "full proof", out[-500:]
    ok, out = run("-tempinduct", "induct")
    if ok:
        return True, "temporal induction (unbounded proof)", out[-500:]
    ok2, out2 = run("-seq 24", "bmc24")
    return ok2, "bounded proof, 24 cycles", (out2 if not ok2 else out2)[-500:]


def build_tb(man, top, n_vec=400):
    ins = [(n, w) for n, w in man["inputs"]]
    outs = [(n, w) for n, w in man["outputs"]]
    seq = man["seq"]
    decl = []
    for n, w in ins:
        decl.append(f"  reg {'[%d:0] ' % (w - 1) if w > 1 else ''}{n};")
    for n, w in outs:
        rng = "[%d:0] " % (w - 1) if w > 1 else ""
        decl.append(f"  wire {rng}{n}_g;")
        decl.append(f"  wire {rng}{n}_n;")
    conn_g = ([".clk(clk)"] if seq else []) + [f".{n}({n})" for n, _ in ins] + [f".{n}({n}_g)" for n, _ in outs]
    conn_n = ([".clk(clk)"] if seq else []) + [f".{n}({n})" for n, _ in ins] + [f".{n}({n}_n)" for n, _ in outs]
    init = "\n".join(f"    {n} = 0;" for n, _ in ins)
    rnd = []
    for n, _ in ins:
        if seq and n == "rst":
            rnd.append(f"      rst = (i < 2) ? 1'b1 : (($random % 16) == 0);")
        else:
            rnd.append(f"      {n} = $random;")
    cmp_lines = []
    for n, _ in outs:
        cmp_lines.append(f"""      if ({n}_g !== {n}_n) begin
        errors = errors + 1;
        if (errors < 4) $display("MISMATCH vec=%0d {n}: gold=%h gate=%h", i, {n}_g, {n}_n);
      end""")
    tick = "      clk = 1'b1; #1; clk = 1'b0; #1;" if seq else "      #1;"
    return f"""`timescale 1ns/1ps
module tb;
  integer errors;
  integer i;
  reg clk;
{chr(10).join(decl)}
  {top} dut_g({", ".join(conn_g)});
  {top}_gate dut_n({", ".join(conn_n)});
  initial begin
    errors = 0;
    clk = 1'b0;
{init}
    for (i = 0; i < {n_vec}; i = i + 1) begin
{chr(10).join(rnd)}
      #1;
{tick}
{chr(10).join(cmp_lines)}
    end
    $display("ERRORS %0d", errors);
    $finish;
  end
endmodule
"""


def simulate(gold, netlist, cells, man, top, tmp):
    gate = tmp / f"{top}_gate.v"
    text = netlist.read_text()
    text = re.sub(r"\bmodule\s+" + re.escape(top) + r"\b", f"module {top}_gate", text, count=1)
    gate.write_text(text)
    tb = tmp / f"tb_{top}.v"
    tb.write_text(build_tb(man, top))
    exe = tmp / f"sim_{top}"
    rc, out = sh([str(IVERILOG), "-o", str(exe), str(gold), str(gate), str(cells), str(tb)], timeout=600)
    if rc != 0:
        return None, f"compilation failed: {out[-200:]}"
    rc, out = sh([str(VVP), str(exe)], timeout=900)
    m = re.search(r"ERRORS (\d+)", out)
    if not m:
        return None, f"simulation produced no result: {out[-200:]}"
    return int(m.group(1)), out[-200:] if m.group(1) != "0" else ""


def ref_area(gold, top, tmp):
    # note: no -q here — it suppresses the stat report entirely, and stat prints "<n> cells",
    # not "Number of cells: <n>"
    script = tmp / f"area_{top}.ys"
    script.write_text(f"read_verilog {gold}\nsynth -top {top}\nstat\n")
    rc, out = sh([str(YOSYS), "-s", str(script)], timeout=900)
    m = re.search(r"^\s*(\d+)\s+cells\s*$", out, re.M)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--synth-cmd", default=None,
                    help='calibration: command template with {src} and {out} instead of run_synth.sh')
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="synthv_"))
    man = json.loads((HERE / "manifest.json").read_text())
    cells = DESIGNS / "cells.v"
    checks, metrics = {}, {}

    if not a.synth_cmd:
        checks["entrypoint"] = {"pass": (ws / "run_synth.sh").exists(), "detail": "run_synth.sh"}
    if not a.skip_env_check:
        rc, out = sh("pip list 2>/dev/null | awk '{print tolower($1)}'; command -v yosys iverilog abc", cwd=str(ws))
        bad = [p for p in FORBIDDEN_PKGS if p in out.split()]
        if re.search(r"(?m)^\S*/(yosys|iverilog|abc)$", out):
            bad.append("EDA tools on PATH")
        checks["env_constraints"] = {"pass": not bad, "detail": "violations: " + ", ".join(bad) if bad else "ok"}

    per, legal_ok, proved_ok, sim_ok = {}, 0, 0, 0
    for name, m in man.items():
        top = m["top"]
        gold = DESIGNS / f"{name}.v"
        netlist = tmp / f"{name}_net.v"
        cmd = (a.synth_cmd.format(src=gold, out=netlist) if a.synth_cmd
               else f'bash "{ws}/run_synth.sh" "{gold}" "{netlist}"')
        rc, out = sh(cmd, cwd=str(tmp), timeout=1200)
        rec = {"seq": m["seq"], "rc": rc}
        if not netlist.exists() or not netlist.read_text().strip():
            rec.update({"legal": False, "proved": False, "sim_errors": None,
                        "why": f"no netlist produced: {out[-150:]}"})
            per[name] = rec
            continue
        problems, n_cells = check_legality(netlist.read_text(), top)
        rec["legal"] = not problems
        rec["cells"] = n_cells
        if problems:
            rec["legality_problems"] = problems[:4]
        legal_ok += rec["legal"]
        proved, method, log = yosys_equiv(gold, netlist, cells, top, m["seq"], tmp)
        rec["proved"] = proved
        rec["method"] = method
        if not proved:
            rec["equiv_log"] = log[-200:]
        proved_ok += proved
        errs, why = simulate(gold, netlist, cells, m, top, tmp)
        rec["sim_errors"] = errs
        if errs == 0:
            sim_ok += 1
        elif why:
            rec["sim_detail"] = why[:150]
        ref = ref_area(gold, top, tmp)
        rec["ref_cells"] = ref
        if ref and n_cells:
            rec["area_ratio"] = round(n_cells / ref, 2)
        per[name] = rec

    n = len(man)
    metrics["per_design"] = per
    metrics["n_designs"] = n
    # Count only designs that were proven. An unproven netlist may have degenerated to almost nothing: in one
    # haiku4.5 run mult4 had 1 gate (reference 69) and barrel8 had 0 (reference 80), which pulled the median
    # area ratio down to 0.74, looking better than a production synthesiser. Area is informational, but counting
    # wrong netlists creates a false impression: area means something only when the function is correct.
    ratios = [r["area_ratio"] for r in per.values() if r.get("area_ratio") and r.get("proved")]
    metrics["area_ratio_median"] = round(sorted(ratios)[len(ratios) // 2], 2) if ratios else None
    checks["netlist_legality"] = {
        "pass": legal_ok >= 0.9 * n,
        "detail": f"{legal_ok}/{n} legal; " + "; ".join(
            f"{k}: {v.get('legality_problems', [v.get('why', '')])[0]}" for k, v in per.items() if not v.get("legal"))[:300]}
    checks["formal_equivalence"] = {
        "pass": proved_ok >= 0.9 * n,
        "detail": f"{proved_ok}/{n} formally proven equivalent; unproven: " + ", ".join(k for k, v in per.items() if not v.get("proved"))}
    # No tolerance here, unlike the two gates above. A simulation mismatch is a *counterexample*:
    # the netlist provably computes something the RTL does not. That is different from a design
    # the SAT solver merely failed to prove within budget, which is what the 0.9 slack on
    # formal_equivalence is for. Scoring a run full marks while holding a witnessed functional
    # bug is a false positive, and 0.9*13 = 11.7 let exactly that through (12/13 passed).
    checks["simulation_differential"] = {
        "pass": sim_ok == n,
        "detail": f"{sim_ok}/{n} simulations match cycle by cycle; mismatched: " +
                  ", ".join(f"{k}({v['sim_errors']})" for k, v in per.items() if v.get("sim_errors"))}
    checks["area_reported"] = {
        "pass": True, "informational": True,
        "detail": f"median area ratio {metrics['area_ratio_median']}x against a production synthesiser (informational)"}

    required = {k: v for k, v in checks.items() if not v.get("informational")}
    npass = sum(1 for c in required.values() if c["pass"])
    result = {"pass": npass == len(required), "score": f"{npass}/{len(required)}",
              "checks": checks, "metrics": metrics}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
