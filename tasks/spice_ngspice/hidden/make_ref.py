#!/usr/bin/env python3
"""Generate ngspice reference outputs for every hidden netlist: ref/<name>.csv with the columns the spec requires."""
import pathlib, re, subprocess, sys, tempfile, os
HERE = pathlib.Path(__file__).resolve().parent
NG = sys.argv[1] if len(sys.argv) > 1 else "ngspice"

def nodes_and_sources(text):
    nodes, vs = [], []
    for l in text.splitlines():
        l = l.strip()
        if not l or l.startswith(("*", ".")): continue
        p = l.split(); el = p[0].upper()
        k = 4 if el[0] == "M" else 2
        for n in p[1:1 + k]:
            if n != "0" and n not in nodes: nodes.append(n)
        if el[0] == "V": vs.append(p[0])
    return nodes, vs

def analysis(text):
    for l in text.splitlines():
        s = l.strip().lower()
        if s.startswith(".op"): return "op", l
        if s.startswith(".dc"): return "dc", l
        if s.startswith(".tran"): return "tran", l
    raise ValueError("no analysis")

for f in sorted(HERE.glob("netlists/*.cir")):
    text = f.read_text(); nodes, vs = nodes_and_sources(text); kind, line = analysis(text)
    vecs = [f"v({n})" for n in nodes] + [f"i({v})" for v in vs]
    wd = pathlib.Path(tempfile.mkdtemp()); out = wd / "out.txt"
    ctl = f"\n.control\nset wr_singlescale\nset wr_vecnames\nrun\nwrdata {out} {' '.join(vecs)}\nquit\n.endc\n"
    cir = text.replace(".end", ctl + ".end")
    (wd / "in.cir").write_text(cir)
    p = subprocess.run([NG, "-b", str(wd / "in.cir")], capture_output=True, text=True, cwd=wd, timeout=300)
    lines = [l for l in out.read_text().splitlines() if l.strip()]
    hdr = lines[0].split(); rows = [[float(x) for x in l.split()] for l in lines[1:]]
    xname = {"op": None, "dc": "sweep", "tran": "time"}[kind]
    cols = ([xname] if xname else []) + vecs
    csv = ",".join(cols) + "\n"
    for r in rows:
        vals = r[1:] if kind == "op" else r
        csv += ",".join(repr(x) for x in vals) + "\n"
    (HERE / "ref" / f"{f.stem}.csv").write_text(csv)
    print(f.stem, kind, len(rows), "rows", hdr[:4], "stderr:" if p.returncode else "", (p.stderr[-200:] if p.returncode else ""))
