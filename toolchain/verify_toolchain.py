#!/usr/bin/env python3
"""Hidden acceptance suite for the plcforge IEC 61131-3 toolchain.

Eight independent checks; the differential fuzzer carries the most weight because it is the
only assertion source that scales. Nothing here is visible to the building agent.

usage: verify_toolchain.py --workspace <ws> --out <report.json> [--fuzz-n 120] [--quick]
"""
import argparse
import json
import pathlib
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REF = ROOT / "tasks" / "plc_iec61131" / "hidden" / "reference_plc.py"
FUZZ = HERE / "fuzz_st.py"
REGRESS = ROOT / "tasks" / "plc_iec61131" / "hidden"
CYCLE = "10"
PY = sys.executable


def sh(cmd, cwd=None, timeout=300, env=None):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout + p.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def read_trace(p):
    lines = [l.strip() for l in pathlib.Path(p).read_text().splitlines() if l.strip()]
    return [h.strip() for h in lines[0].split(",")], [l.split(",") for l in lines[1:]]


def same(a, b):
    try:
        fa, fb = float(a), float(b)
    except Exception:
        return a.strip() == b.strip()
    if "." in a or "." in b or "e" in a.lower() or "e" in b.lower():
        return abs(fa - fb) <= 1e-6 * max(1.0, abs(fb))
    return fa == fb


def compare_traces(expected, got):
    """returns (ok, first_mismatch)"""
    eh, er = read_trace(expected)
    gh, gr = read_trace(got)
    col = {h: i for i, h in enumerate(gh)}
    for k, row in enumerate(er):
        grow = gr[k] if k < len(gr) else []
        for j, h in enumerate(eh):
            v = grow[col[h]] if h in col and col[h] < len(grow) else "MISSING"
            if not same(v, row[j]):
                return False, f"scan {k} {h}: got {v} want {row[j]}"
    if len(gr) < len(er):
        return False, f"trace too short: {len(gr)} < {len(er)}"
    return True, None


# ---------------------------------------------------------------- checks
def check_entrypoints(ws):
    need = ["plc-compile", "plc-run", "plc-ld2st", "plc-xml-export", "plc-xml-import", "plc-serve", "plc-hist"]
    missing = [n for n in need if not (ws / "bin" / n).exists()]
    return {"pass": not missing, "detail": "missing: " + ", ".join(missing) if missing else "all 7 present"}


def check_fuzz(ws, tmp, n, seed):
    d = tmp / "fuzz"
    rc, out = sh([PY, str(FUZZ), "gen", "--out", str(d), "--n", str(n), "--seed", str(seed),
                  "--scans", "100", "--complexity", "3"], timeout=900)
    rc2, out2 = sh([PY, str(FUZZ), "ref", "--dir", str(d)], timeout=1800)
    res_json = tmp / "fuzz_result.json"
    cmd = f'bash "{ws}/bin/plc-run" {{prog}} {{stim}} {{trace}} {{cycle}}'
    rc3, out3 = sh([PY, str(FUZZ), "diff", "--dir", str(d), "--cmd", cmd, "--timeout", "60",
                    "--out", str(res_json)], timeout=5400)
    if not res_json.exists():
        return {"pass": False, "detail": (out3 or out2)[-800:], "rate": 0.0}
    r = json.loads(res_json.read_text())
    return {"pass": r["rate"] >= 0.98, "rate": r["rate"], "total": r["total"], "passed": r["passed"],
            "detail": f'{r["passed"]}/{r["total"]} match; first mismatches: ' +
                      "; ".join(f'{m["case"]}: {m["why"]}' for m in r["mismatches"][:5])}


def check_regression(ws, tmp):
    ok = 0
    names = sorted(p.stem for p in (REGRESS / "programs").glob("*.st"))
    fails = []
    for name in names:
        got = tmp / f"reg_{name}.csv"
        rc, out = sh(f'bash "{ws}/bin/plc-run" "{REGRESS}/programs/{name}.st" '
                     f'"{REGRESS}/programs/{name}.csv" "{got}" {CYCLE}', timeout=300)
        if got.exists():
            good, why = compare_traces(REGRESS / "ref" / f"{name}.csv", got)
            ok += good
            if not good:
                fails.append(f"{name}: {why}")
        else:
            fails.append(f"{name}: no trace ({out[-80:]})")
    return {"pass": ok >= 0.9 * len(names), "detail": f"{ok}/{len(names)} passed; " + "; ".join(fails[:4])}


BAD_PROGRAMS = {
    "undeclared": ("PROGRAM P\nVAR_OUTPUT\n  a : BOOL;\nEND_VAR\na := undeclared_thing;\nEND_PROGRAM\n", 5),
    "assign_to_input": ("PROGRAM P\nVAR_INPUT\n  x : BOOL;\nEND_VAR\nVAR_OUTPUT\n  y : BOOL;\nEND_VAR\nx := TRUE;\ny := x;\nEND_PROGRAM\n", 7),
    "type_mismatch": ("PROGRAM P\nVAR_OUTPUT\n  n : INT;\nEND_VAR\nVAR\n  b : BOOL;\nEND_VAR\nn := b AND TRUE;\nEND_PROGRAM\n", 7),
    "fb_undeclared": ("PROGRAM P\nVAR_OUTPUT\n  q : BOOL;\nEND_VAR\nt1(IN := TRUE, PT := T#1s);\nq := t1.Q;\nEND_PROGRAM\n", 5),
    "dup_case": ("PROGRAM P\nVAR_OUTPUT\n  n : INT;\nEND_VAR\nVAR\n  s : INT;\nEND_VAR\nCASE s OF\n  1: n := 1;\n  1: n := 2;\nELSE\n  n := 0;\nEND_CASE;\nEND_PROGRAM\n", 9),
}


def check_diagnostics(ws, tmp):
    caught = 0
    detail = []
    for name, (src, line) in BAD_PROGRAMS.items():
        f = tmp / f"bad_{name}.st"
        f.write_text(src)
        outj = tmp / f"bad_{name}.json"
        rc, out = sh(f'bash "{ws}/bin/plc-compile" "{f}" "{outj}"', timeout=180)
        errs = []
        if outj.exists():
            try:
                errs = [d for d in json.loads(outj.read_text()).get("diagnostics", [])
                        if d.get("severity") == "error"]
            except Exception:
                errs = []
        # a missing compiler also exits non-zero: require a real diagnostics payload, not just rc
        flagged = bool(errs)
        near = any(abs((d.get("line") or -99) - line) <= 1 for d in errs)
        caught += bool(flagged)
        detail.append(f"{name}: {'flagged' if flagged else 'missed'}{'(line ok)' if near else ''}")
    return {"pass": caught == len(BAD_PROGRAMS), "detail": f"{caught}/{len(BAD_PROGRAMS)} caught; " + "; ".join(detail)}


LD_CASES = {
    "seal_in": {
        "rungs": {"program": "SealIn",
                  "vars": [{"name": "Start", "kind": "input", "type": "BOOL", "init": None},
                           {"name": "Stop", "kind": "input", "type": "BOOL", "init": None},
                           {"name": "Motor", "kind": "output", "type": "BOOL", "init": None}],
                  "rungs": [{"comment": "start/stop seal-in",
                             "elements": [[{"type": "contact", "var": "Start", "negated": False},
                                           {"type": "contact", "var": "Motor", "negated": False}],
                                          [{"type": "contact", "var": "Stop", "negated": True}]],
                             "output": {"type": "coil", "var": "Motor", "mode": "normal"}}]},
        "st": """PROGRAM SealIn
VAR_INPUT
  Start : BOOL;
  Stop : BOOL;
END_VAR
VAR_OUTPUT
  Motor : BOOL;
END_VAR
Motor := (Start OR Motor) AND NOT Stop;
END_PROGRAM
"""},
    "interlock": {
        "rungs": {"program": "Interlock",
                  "vars": [{"name": "A", "kind": "input", "type": "BOOL", "init": None},
                           {"name": "B", "kind": "input", "type": "BOOL", "init": None},
                           {"name": "C", "kind": "input", "type": "BOOL", "init": None},
                           {"name": "Out1", "kind": "output", "type": "BOOL", "init": None},
                           {"name": "Out2", "kind": "output", "type": "BOOL", "init": None}],
                  "rungs": [{"comment": "A and (B or not C)",
                             "elements": [[{"type": "contact", "var": "A", "negated": False}],
                                          [{"type": "contact", "var": "B", "negated": False},
                                           {"type": "contact", "var": "C", "negated": True}]],
                             "output": {"type": "coil", "var": "Out1", "mode": "normal"}},
                            {"comment": "set/reset",
                             "elements": [[{"type": "contact", "var": "B", "negated": False}]],
                             "output": {"type": "coil", "var": "Out2", "mode": "set"}},
                            {"comment": "reset on C",
                             "elements": [[{"type": "contact", "var": "C", "negated": False}]],
                             "output": {"type": "coil", "var": "Out2", "mode": "reset"}}]},
        "st": """PROGRAM Interlock
VAR_INPUT
  A : BOOL;
  B : BOOL;
  C : BOOL;
END_VAR
VAR_OUTPUT
  Out1 : BOOL;
  Out2 : BOOL;
END_VAR
Out1 := A AND (B OR NOT C);
IF B THEN Out2 := TRUE; END_IF;
IF C THEN Out2 := FALSE; END_IF;
END_PROGRAM
"""},
}


def make_stim(names, scans, seed):
    rng = random.Random(seed)
    rows = [",".join(names)]
    state = {n: 0 for n in names}
    for _ in range(scans):
        for n in names:
            if rng.random() < 0.25:
                state[n] = 1 - state[n]
        rows.append(",".join(str(state[n]) for n in names))
    return "\n".join(rows) + "\n"


def check_ladder(ws, tmp):
    ok, detail = 0, []
    for name, case in LD_CASES.items():
        d = tmp / f"ld_{name}"
        d.mkdir(exist_ok=True)
        (d / "rungs.json").write_text(json.dumps(case["rungs"]))
        (d / "ref.st").write_text(case["st"])
        ins = [v["name"] for v in case["rungs"]["vars"] if v["kind"] == "input"]
        (d / "stim.csv").write_text(make_stim(ins, 90, hash(name) % 1000))
        rc, out = sh(f'bash "{ws}/bin/plc-ld2st" "{d}/rungs.json" "{d}/gen.st"', timeout=180)
        if not (d / "gen.st").exists():
            detail.append(f"{name}: no ST produced ({out[-60:]})")
            continue
        sh([PY, str(REF), str(d / "ref.st"), str(d / "stim.csv"), str(d / "expected.csv"), CYCLE], timeout=300)
        rc2, out2 = sh(f'bash "{ws}/bin/plc-run" "{d}/gen.st" "{d}/stim.csv" "{d}/got.csv" {CYCLE}', timeout=300)
        if not (d / "got.csv").exists() or not (d / "expected.csv").exists():
            detail.append(f"{name}: no trace")
            continue
        good, why = compare_traces(d / "expected.csv", d / "got.csv")
        ok += good
        if not good:
            detail.append(f"{name}: {why}")
    return {"pass": ok == len(LD_CASES), "detail": f"{ok}/{len(LD_CASES)} equivalent; " + "; ".join(detail[:3])}


def check_xml_roundtrip(ws, tmp, n=6):
    d = tmp / "xmlrt"
    rc, _ = sh([PY, str(FUZZ), "gen", "--out", str(d), "--n", str(n), "--seed", "991",
                "--scans", "60", "--complexity", "2"], timeout=600)
    sh([PY, str(FUZZ), "ref", "--dir", str(d)], timeout=900)
    ok, detail = 0, []
    cases = [c for c in sorted(d.iterdir()) if (c / "expected.csv").exists()]
    for c in cases:
        rc1, o1 = sh(f'bash "{ws}/bin/plc-xml-export" "{c}/prog.st" "{c}/p.xml"', timeout=180)
        rc2, o2 = sh(f'bash "{ws}/bin/plc-xml-import" "{c}/p.xml" "{c}/back.st"', timeout=180)
        if not (c / "back.st").exists():
            detail.append(f"{c.name}: round trip failed ({(o1 + o2)[-60:]})")
            continue
        try:
            import xml.etree.ElementTree as ET
            root = ET.parse(c / "p.xml").getroot()
            tags = {e.tag.split('}')[-1] for e in root.iter()}
            if not {"pou", "interface", "body"} <= tags:
                detail.append(f"{c.name}: XML lacks the basic PLCopen structure")
                continue
        except Exception as e:
            detail.append(f"{c.name}: XML invalid {str(e)[:40]}")
            continue
        rc3, o3 = sh(f'bash "{ws}/bin/plc-run" "{c}/back.st" "{c}/stim.csv" "{c}/rt.csv" {CYCLE}', timeout=300)
        if not (c / "rt.csv").exists():
            detail.append(f"{c.name}: cannot execute after the round trip")
            continue
        good, why = compare_traces(c / "expected.csv", c / "rt.csv")
        ok += good
        if not good:
            detail.append(f"{c.name}: {why}")
    return {"pass": bool(cases) and ok == len(cases), "detail": f"{ok}/{len(cases)} round-trip equivalent; " + "; ".join(detail[:3])}


MODBUS_PROG = """PROGRAM ModbusDemo
VAR_INPUT
  Start : BOOL;
  Level : INT;
END_VAR
VAR_OUTPUT
  Motor : BOOL;
  Alarm : BOOL;
  Count : INT;
END_VAR
VAR
  edge : R_TRIG;
END_VAR
edge(CLK := Start);
IF edge.Q THEN Count := Count + 1; END_IF;
Motor := Start AND (Level < 80);
Alarm := Level >= 80;
END_PROGRAM
"""


def check_modbus(ws, tmp, oracle_py):
    d = tmp / "modbus"
    d.mkdir(exist_ok=True)
    (d / "prog.st").write_text(MODBUS_PROG)
    scans = 60
    rng = random.Random(5)
    rows = ["Start,Level"]
    for k in range(scans):
        rows.append(f"{1 if (k // 7) % 2 else 0},{rng.randint(0, 120)}")
    (d / "stim.csv").write_text("\n".join(rows) + "\n")
    mapping = {"coils": {"0": "Motor", "1": "Alarm"}, "discrete_inputs": {"0": "Start"},
               "holding_registers": {"0": "Count"}, "input_registers": {"0": "Level"}}
    (d / "map.json").write_text(json.dumps(mapping))
    sh([PY, str(REF), str(d / "prog.st"), str(d / "stim.csv"), str(d / "expected.csv"), CYCLE], timeout=300)
    port = random.randint(15000, 25000)
    srv = subprocess.Popen(["bash", str(ws / "bin" / "plc-serve"), str(d / "prog.st"), str(d / "stim.csv"),
                            "200", str(port), str(d / "map.json")],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(6)
    client = d / "client.py"
    client.write_text(f'''
import json, sys, time
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient("127.0.0.1", port={port}, timeout=5)
ok = c.connect()
res = {{"connected": bool(ok), "samples": [], "readonly_rejected": None}}
for _ in range(6):
    try:
        co = c.read_coils(0, count=2)
        hr = c.read_holding_registers(0, count=1)
        ir = c.read_input_registers(0, count=1)
        di = c.read_discrete_inputs(0, count=1)
        res["samples"].append({{"motor": int(co.bits[0]), "alarm": int(co.bits[1]),
                               "count": hr.registers[0], "level": ir.registers[0], "start": int(di.bits[0])}})
    except Exception as e:
        res["samples"].append({{"error": str(e)[:80]}})
    time.sleep(0.4)
try:
    w = c.write_register(0, 4242)
    res["write_hr_ok"] = not getattr(w, "isError", lambda: False)()
    hr = c.read_holding_registers(0, count=1)
    res["hr_after_write"] = hr.registers[0]
except Exception as e:
    res["write_hr_ok"] = False; res["hr_err"] = str(e)[:80]
c.close()
json.dump(res, open(sys.argv[1], "w"))
''')
    rc, out = sh(f'"{oracle_py}" "{client}" "{d}/client_out.json"', timeout=180)
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()
    if not (d / "client_out.json").exists():
        return {"pass": False, "detail": f"client produced no result: {out[-200:]}"}
    r = json.loads((d / "client_out.json").read_text())
    if not r.get("connected"):
        return {"pass": False, "detail": "cannot connect to the server"}
    good = [s for s in r["samples"] if "error" not in s]
    if not good:
        return {"pass": False, "detail": f"all reads failed: {r['samples'][:1]}"}
    eh, er = read_trace(d / "expected.csv")
    ci = {h: i for i, h in enumerate(eh)}
    consistent = 0
    for s in good:
        for row in er:
            if (int(row[ci["Motor"]]) == s["motor"] and int(row[ci["Alarm"]]) == s["alarm"]
                    and int(row[ci["Count"]]) == s["count"]):
                consistent += 1
                break
    ok = consistent >= max(1, len(good) - 1) and r.get("write_hr_ok")
    return {"pass": bool(ok), "detail": f"connected, {consistent}/{len(good)} readings match the reference trace, "
                                        f"holding-register write {'ok' if r.get('write_hr_ok') else 'failed'}"}


def check_historian(ws, tmp):
    d = tmp / "hist"
    d.mkdir(exist_ok=True)
    rng = random.Random(3)
    rows = ["Motor,Level"]
    motor, vals, mot = [], [], 0
    for k in range(200):
        if rng.random() < 0.12:
            mot = 1 - mot
        lv = rng.randint(0, 100)
        motor.append(mot)
        vals.append(lv)
        rows.append(f"{mot},{lv}")
    (d / "trace.csv").write_text("\n".join(rows) + "\n")
    trans = [{"scan": i, "from": motor[i - 1], "to": motor[i]} for i in range(1, len(motor)) if motor[i] != motor[i - 1]]
    queries = [
        ({"type": "aggregate", "var": "Level", "fn": "max", "from_scan": 0, "to_scan": 199}, max(vals)),
        ({"type": "aggregate", "var": "Level", "fn": "mean", "from_scan": 0, "to_scan": 199}, sum(vals) / len(vals)),
        ({"type": "duty_cycle", "var": "Motor", "from_scan": 0, "to_scan": 199}, sum(motor) / len(motor)),
        ({"type": "transitions", "var": "Motor"}, trans),
    ]
    ok, detail = 0, []
    for i, (q, want) in enumerate(queries):
        (d / f"q{i}.json").write_text(json.dumps(q))
        rc, out = sh(f'bash "{ws}/bin/plc-hist" "{d}/trace.csv" "{d}/q{i}.json" "{d}/a{i}.json"', timeout=180)
        if not (d / f"a{i}.json").exists():
            detail.append(f"{q['type']}: no output")
            continue
        got = json.loads((d / f"a{i}.json").read_text())
        # the spec does not mandate a wrapper: accept a bare value/list or a {"value"|"result"|<type>} object
        if isinstance(got, dict):
            val = got.get("value", got.get("result", got.get(q["type"], got)))
        else:
            val = got
        good = False
        if q["type"] == "transitions":
            gl = val if isinstance(val, list) else (got.get("transitions", []) if isinstance(got, dict) else [])
            good = len(gl) == len(want) and all(int(a.get("scan", -1)) == b["scan"] for a, b in zip(gl, want))
        else:
            try:
                good = abs(float(val) - float(want)) <= 1e-6 * max(1.0, abs(want))
            except Exception:
                good = False
        ok += good
        if not good:
            detail.append(f"{q['type']}: got {str(val)[:60]} want {str(want)[:60]}")
    return {"pass": ok == len(queries), "detail": f"{ok}/{len(queries)} queries correct; " + "; ".join(detail[:3])}


def check_ir_contract(ws, tmp):
    """M1's IR must be consumable on its own: all fields present, variables and FB declarations readable"""
    src = REGRESS / "programs" / "conveyor_count.st"
    out = tmp / "ir.json"
    rc, o = sh(f'bash "{ws}/bin/plc-compile" "{src}" "{out}"', timeout=180)
    if not out.exists():
        return {"pass": False, "detail": f"no IR produced: {o[-150:]}"}
    try:
        ir = json.loads(out.read_text())
    except Exception as e:
        return {"pass": False, "detail": f"IR is not valid JSON: {str(e)[:80]}"}
    names = {v["name"] for v in ir.get("vars", []) if isinstance(v, dict) and "name" in v}
    kinds = {v["name"]: v.get("kind") for v in ir.get("vars", []) if isinstance(v, dict) and "name" in v}
    fbk = {f.get("name"): f.get("kind") for f in ir.get("fbs", [])} if isinstance(ir.get("fbs"), list) else {}
    need_vars = {"Run", "Sensor", "Reset", "Belt", "Count", "BatchDone", "Elapsed"}
    missing = need_vars - names
    ok = (not missing and ir.get("program") and isinstance(ir.get("body"), list) and ir["body"]
          and kinds.get("Run") == "input" and kinds.get("Belt") == "output"
          and ("startDelay" in fbk or "startDelay" in names))
    return {"pass": bool(ok), "detail": f"program={ir.get('program')} vars={len(names)} body={len(ir.get('body', []))} "
                                        f"fbs={fbk or '-'} missing={sorted(missing) or 'none'}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fuzz-n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="tcverify_"))
    oracle_py = ROOT / "envs" / "industrial_oracle" / "bin" / "python"

    checks = {}
    checks["entrypoints"] = check_entrypoints(ws)
    checks["ir_contract"] = check_ir_contract(ws, tmp)
    checks["diagnostics"] = check_diagnostics(ws, tmp)
    checks["regression_suite"] = check_regression(ws, tmp)
    checks["ladder_equivalence"] = check_ladder(ws, tmp)
    checks["plcopen_xml_roundtrip"] = check_xml_roundtrip(ws, tmp, n=4 if a.quick else 6)
    checks["historian"] = check_historian(ws, tmp)
    try:
        checks["modbus_conformance"] = check_modbus(ws, tmp, oracle_py)
    except Exception as e:
        checks["modbus_conformance"] = {"pass": False, "detail": f"checker raised: {str(e)[:200]}"}
    checks["differential_fuzz"] = check_fuzz(ws, tmp, 20 if a.quick else a.fuzz_n, a.seed)

    npass = sum(1 for c in checks.values() if c["pass"])
    result = {"pass": npass == len(checks), "score": f"{npass}/{len(checks)}", "checks": checks}
    pathlib.Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["pass"] for k, v in checks.items()}, ensure_ascii=False),
          result["score"], "PASS" if result["pass"] else "FAIL")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
