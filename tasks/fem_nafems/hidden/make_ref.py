#!/usr/bin/env python3
"""Run CalculiX on each hidden model; store nodal displacements / eigenfrequencies as reference (ref/<model>.json)."""
import json, pathlib, re, subprocess, shutil, tempfile, os
HERE = pathlib.Path(__file__).resolve().parent
for inp in sorted(HERE.glob("models/*.inp")):
    wd = pathlib.Path(tempfile.mkdtemp()); shutil.copy(inp, wd / "job.inp")
    p = subprocess.run(["ccx", "-i", "job"], cwd=wd, capture_output=True, text=True, timeout=1800, env={**os.environ, "OMP_NUM_THREADS": "4"})
    dat = (wd / "job.dat").read_text() if (wd / "job.dat").exists() else ""
    ref = {"model": inp.stem}
    disp = {}
    m = re.search(r"displacements .*?\n\n(.*?)(?:\n\n|\Z)", dat, re.S)
    if m:
        for l in m.group(1).splitlines():
            parts = l.split()
            if len(parts) >= 3 and parts[0].isdigit(): disp[int(parts[0])] = [float(parts[1]), float(parts[2])]
    ref["displacements"] = disp
    if "E I G E N V A L U E" in dat:
        freqs = []
        for l in dat.split("E I G E N V A L U E", 1)[1].splitlines():
            m2 = re.match(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", l)
            if m2: freqs.append(float(m2.group(4)))
        ref["frequencies_hz"] = freqs
    (HERE / "ref" / f"{inp.stem}.json").write_text(json.dumps(ref))
    print(inp.stem, "rc", p.returncode, "nodes", len(disp), "freqs", ref.get("frequencies_hz", [])[:4], "" if p.returncode == 0 else (p.stdout + p.stderr)[-300:])
