#!/usr/bin/env python3
"""Build the hidden scenario set for scada_dcs and its reference answers.

Emits, into hidden/:
    scenarios/<name>.json          the scenario handed to the candidate
    ref/<name>.json                the reference answer from ref_scada
    examples/<name>.scenario.json  three worked examples copied into the workspace
    examples/<name>.expected.json
    manifest.json

Guards, each earned from a defect on an earlier task in this suite:

  * the reference must run without raising, and its journal must already be in the sorted order the
    spec mandates — an asset whose own answer violates the spec fails every candidate;
  * every alarm must reference a declared tag, every loop's pv and out likewise, and every Modbus
    address must be non-negative — an ill-formed scenario is my defect, not the candidate's;
  * every scenario must actually exercise something: a scenario that produces an empty journal AND
    no loop output AND no query would be graded vacuously.

usage: make_scenarios.py [--out <hidden dir>]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ref_scada import run  # noqa: E402


def base(name, **kw):
    s = {"name": name, "scan_ms": 100, "t_end_ms": 1000,
         "tags": [], "alarms": [], "loops": [], "inputs": [], "queries": [],
         "modbus": {"holding": {}}}
    s.update(kw)
    return s


def ramp(tag, pts):
    return [{"t_ms": t, "tag": tag, "value": v} for (t, v) in pts]


def scenarios():
    S = {}
    TT = {"id": "TT101", "type": "analog", "init": 20.0}
    AO = {"id": "AO1", "type": "analog", "init": 0.0}
    DS = {"id": "XS1", "type": "digital", "init": False}

    # s01 — the floor: one HI alarm, no delay, no deadband
    S["s01_basic"] = base("s01_basic", tags=[TT],
        inputs=ramp("TT101", [(0, 20.0), (300, 95.0), (700, 20.0)]),
        alarms=[{"tag": "TT101", "kind": "HI", "limit": 80.0, "deadband": 0.0,
                 "on_delay_ms": 0, "off_delay_ms": 0, "priority": 2}],
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "max"}])

    # s02 — on-delay fires on the third scan of the condition, not the fourth
    S["s02_on_delay"] = base("s02_on_delay", tags=[TT],
        inputs=ramp("TT101", [(0, 20.0), (200, 90.0)]),
        alarms=[{"tag": "TT101", "kind": "HI", "limit": 80.0, "deadband": 0.0,
                 "on_delay_ms": 300, "off_delay_ms": 0, "priority": 2}],
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "count"}])

    # s03 — condition breaks one scan before the delay expires: NO event at all
    S["s03_delay_aborted"] = base("s03_delay_aborted", tags=[TT],
        inputs=ramp("TT101", [(0, 20.0), (200, 90.0), (400, 10.0), (600, 90.0), (700, 10.0)]),
        alarms=[{"tag": "TT101", "kind": "HI", "limit": 80.0, "deadband": 0.0,
                 "on_delay_ms": 300, "off_delay_ms": 0, "priority": 2}],
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "min"}])

    # s04 — deadband suppresses chatter: without it this journal would have extra events
    S["s04_deadband"] = base("s04_deadband", tags=[TT],
        inputs=ramp("TT101", [(0, 20.0), (100, 90.0), (300, 82.0), (500, 78.0),
                              (700, 74.0), (900, 90.0)]),
        alarms=[{"tag": "TT101", "kind": "HI", "limit": 80.0, "deadband": 5.0,
                 "on_delay_ms": 0, "off_delay_ms": 0, "priority": 1}],
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "avg"}])

    # s05 — several alarms on one tag: ordering by (t, priority, tag, kind) matters
    S["s05_priority"] = base("s05_priority", tags=[TT],
        inputs=ramp("TT101", [(0, 20.0), (200, 120.0), (600, 20.0)]),
        alarms=[{"tag": "TT101", "kind": "HI", "limit": 80.0, "deadband": 0.0,
                 "on_delay_ms": 0, "off_delay_ms": 0, "priority": 3},
                {"tag": "TT101", "kind": "HIHI", "limit": 100.0, "deadband": 0.0,
                 "on_delay_ms": 0, "off_delay_ms": 0, "priority": 1},
                {"tag": "TT101", "kind": "LO", "limit": 25.0, "deadband": 0.0,
                 "on_delay_ms": 0, "off_delay_ms": 0, "priority": 2}],
        queries=[{"tag": "TT101", "from_ms": 200, "to_ms": 600, "agg": "twavg"}])

    # s06 — off-delay: the alarm must stay active through a brief dip
    S["s06_off_delay"] = base("s06_off_delay", tags=[TT],
        inputs=ramp("TT101", [(0, 20.0), (100, 90.0), (400, 20.0), (500, 90.0), (800, 20.0)]),
        alarms=[{"tag": "TT101", "kind": "HI", "limit": 80.0, "deadband": 0.0,
                 "on_delay_ms": 0, "off_delay_ms": 300, "priority": 2}],
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "count"}])

    # s07 — PID that never saturates
    S["s07_pid"] = base("s07_pid", t_end_ms=600, tags=[TT, AO],
        inputs=ramp("TT101", [(0, 40.0), (300, 48.0)]),
        loops=[{"id": "PIC1", "pv": "TT101", "sp": 50.0, "kp": 1.2, "ki": 0.5, "kd": 0.05,
                "out_min": -100.0, "out_max": 100.0, "out": "AO1"}],
        queries=[{"tag": "AO1", "from_ms": 0, "to_ms": 600, "agg": "max"}])

    # s08 — PID that saturates: without the integral rollback the output trajectory differs
    S["s08_pid_windup"] = base("s08_pid_windup", t_end_ms=800, tags=[TT, AO],
        inputs=ramp("TT101", [(0, 0.0)]),
        loops=[{"id": "PIC1", "pv": "TT101", "sp": 100.0, "kp": 1.0, "ki": 10.0, "kd": 0.0,
                "out_min": 0.0, "out_max": 50.0, "out": "AO1"}],
        queries=[{"tag": "AO1", "from_ms": 0, "to_ms": 800, "agg": "min"}])

    # s09 — historian: twavg and avg must differ materially over an uneven window
    S["s09_historian"] = base("s09_historian", t_end_ms=1000, tags=[TT],
        inputs=ramp("TT101", [(0, 10.0), (700, 90.0)]),
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "avg"},
                 {"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "twavg"},
                 {"tag": "TT101", "from_ms": 300, "to_ms": 800, "agg": "twavg"},
                 {"tag": "TT101", "from_ms": 0, "to_ms": 1000, "agg": "count"},
                 {"tag": "TT101", "from_ms": 400, "to_ms": 600, "agg": "min"}])

    # s10 — Modbus: clamp at the top of the range, a digital tag, and a gap register
    S["s10_modbus"] = base("s10_modbus", t_end_ms=300, tags=[TT, DS, AO],
        inputs=ramp("TT101", [(0, 20.0), (200, 7000.0)]) + [{"t_ms": 100, "tag": "XS1", "value": True}],
        modbus={"holding": {"TT101": 0, "XS1": 3, "AO1": 5}},
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 300, "agg": "max"}])

    # s11 — everything at once
    S["s11_combined"] = base("s11_combined", t_end_ms=1200, tags=[TT, AO, DS],
        inputs=ramp("TT101", [(0, 20.0), (200, 95.0), (600, 60.0), (900, 110.0)])
               + [{"t_ms": 500, "tag": "XS1", "value": True}],
        alarms=[{"tag": "TT101", "kind": "HI", "limit": 80.0, "deadband": 4.0,
                 "on_delay_ms": 200, "off_delay_ms": 100, "priority": 2},
                {"tag": "TT101", "kind": "HIHI", "limit": 100.0, "deadband": 2.0,
                 "on_delay_ms": 0, "off_delay_ms": 0, "priority": 1}],
        loops=[{"id": "PIC1", "pv": "TT101", "sp": 70.0, "kp": 0.8, "ki": 2.0, "kd": 0.1,
                "out_min": 0.0, "out_max": 100.0, "out": "AO1"}],
        modbus={"holding": {"TT101": 0, "AO1": 1, "XS1": 2}},
        queries=[{"tag": "TT101", "from_ms": 0, "to_ms": 1200, "agg": "twavg"},
                 {"tag": "AO1", "from_ms": 0, "to_ms": 1200, "agg": "max"},
                 {"tag": "TT101", "from_ms": 0, "to_ms": 1200, "agg": "count"}])
    return S


def wellformed(name, s):
    ids = {t["id"] for t in s["tags"]}
    for a in s["alarms"]:
        if a["tag"] not in ids:
            raise SystemExit(f"{name}: alarm references an undeclared tag {a['tag']}")
        if a["kind"] not in ("HI", "HIHI", "LO", "LOLO"):
            raise SystemExit(f"{name}: unknown alarm kind {a['kind']}")
        if a.get("deadband", 0.0) < 0:
            raise SystemExit(f"{name}: deadband may not be negative")
        for k in ("on_delay_ms", "off_delay_ms"):
            if a.get(k, 0) % s["scan_ms"]:
                raise SystemExit(f"{name}: {k}={a[k]} is not a multiple of the scan period {s['scan_ms']}, "
                                 f"so event times would depend on rounding rather than the specification")
    for l in s["loops"]:
        if l["pv"] not in ids or (l.get("out") and l["out"] not in ids):
            raise SystemExit(f"{name}: loop {l['id']} references an undeclared tag")
        if l["out_min"] >= l["out_max"]:
            raise SystemExit(f"{name}: loop {l['id']} has invalid output limits")
    for ev in s["inputs"]:
        if ev["tag"] not in ids:
            raise SystemExit(f"{name}: input event references an undeclared tag {ev['tag']}")
        if ev["t_ms"] % s["scan_ms"]:
            raise SystemExit(f"{name}: input time {ev['t_ms']} does not fall on a scan point, "
                             f"so the zero-order-hold result would depend on implementation details rather than the specification")
    for tag, addr in s["modbus"].get("holding", {}).items():
        if tag not in ids or addr < 0:
            raise SystemExit(f"{name}: illegal Modbus mapping {tag}->{addr}")
    for q in s["queries"]:
        if q["tag"] not in ids:
            raise SystemExit(f"{name}: query references an undeclared tag {q['tag']}")
        if q["from_ms"] > q["to_ms"]:
            raise SystemExit(f"{name}: query window is reversed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    for sub in ("scenarios", "ref", "examples"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, s in scenarios().items():
        wellformed(name, s)
        r = run(s)
        j = r["alarm_journal"]
        want = sorted(j, key=lambda e: (e["t_ms"], e["priority"], e["tag"], e["kind"]))
        if j != want:
            raise SystemExit(f"{name}: the reference journal is not sorted per the specification; fix the asset first")
        for reg in r["modbus_registers"]:
            if not (0 <= reg <= 65535):
                raise SystemExit(f"{name}: register value {reg} is out of range")
        if not j and not r["loop_outputs"] and not r["historian"]:
            raise SystemExit(f"{name}: this scenario checks nothing -- an empty check")
        (out / "scenarios" / f"{name}.json").write_text(json.dumps(s, indent=1))
        (out / "ref" / f"{name}.json").write_text(json.dumps(r, indent=1))
        manifest.append(name)
        nloop = sum(len(v) for v in r["loop_outputs"].values())
        print("%-20s alarms=%-3d loop samples=%-4d queries=%-2d registers=%d" % (
            name, len(j), nloop, len(r["historian"]), len(r["modbus_registers"])))

    for name in ("s01_basic", "s04_deadband", "s09_historian"):
        s = json.loads((out / "scenarios" / f"{name}.json").read_text())
        r = json.loads((out / "ref" / f"{name}.json").read_text())
        (out / "examples" / f"{name}.scenario.json").write_text(json.dumps(s, indent=1))
        (out / "examples" / f"{name}.expected.json").write_text(json.dumps(r, indent=1))

    (out / "manifest.json").write_text(json.dumps({"scenarios": manifest}, indent=1))
    print(f"\n{len(manifest)} scenarios written to {out}")


if __name__ == "__main__":
    main()
