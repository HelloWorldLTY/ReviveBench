#!/usr/bin/env python3
"""Reference SCADA/DCS runtime — oracle for scada_dcs, and the calibration kernel.

Everything here is deterministic integer-timed logic, so the reference answer is not an
approximation of the truth, it *is* the truth as the spec defines it. That places the whole burden
on the spec being unambiguous and this file matching it exactly, which is why the self-test beside
it checks hand-computed event sequences rather than merely re-running this code.

The four places the spec is deliberately subtle, and therefore the four places to read carefully:

  * phase order within a scan (input, alarms, loops, historian) and the rule that a loop's output
    is visible only on the NEXT scan;
  * the alarm deadband is asymmetric — it widens the clear threshold, never the trip threshold —
    which is what stops a signal hovering at the limit from chattering;
  * the on-delay clock starts at the scan where the latched condition first became true, so
    on_delay_ms=300 with scan_ms=100 fires on the third scan of the condition, not the fourth;
  * anti-windup rolls the integral back to its pre-update value when the raw output saturates.

usage: ref_scada.py <scenario.json> <out.json>
"""
import json
import math
import pathlib
import sys


def _round_half_away(x):
    """Round half away from zero, as §6 requires. Python's round() is banker's rounding."""
    return int(math.floor(x + 0.5)) if x >= 0 else int(math.ceil(x - 0.5))


class Engine:
    def __init__(self, scen):
        self.scen = scen
        self.scan = scen["scan_ms"]
        self.t_end = scen["t_end_ms"]
        self.tags = {t["id"]: dict(t) for t in scen["tags"]}
        self.value = {t["id"]: t.get("init", 0.0) for t in scen["tags"]}
        # inputs bucketed by tag, sorted by time, for the zero-order hold
        self.inputs = {}
        for ev in sorted(scen.get("inputs", []), key=lambda e: e["t_ms"]):
            self.inputs.setdefault(ev["tag"], []).append((ev["t_ms"], ev["value"]))
        self.alarms = [dict(a) for a in scen.get("alarms", [])]
        for a in self.alarms:
            a["_latched"] = False      # latched condition (post-deadband)
            a["_active"] = False       # has an ACT been emitted and not yet cleared
            a["_since_true"] = None    # scan time the latched condition became true
            a["_since_false"] = None
        self.loops = [dict(l) for l in scen.get("loops", [])]
        for l in self.loops:
            l["_I"] = 0.0
            l["_e_prev"] = None
        self.journal = []
        self.loop_out = {l["id"]: [] for l in self.loops}
        self.history = {t["id"]: [] for t in scen["tags"]}
        self.pending_writes = {}

    # ---------------------------------------------------------------- phases

    def phase_input(self, t):
        for tag, seq in self.inputs.items():
            latest = None
            for (ts, v) in seq:
                if ts <= t:
                    latest = v
                else:
                    break
            if latest is not None:
                self.value[tag] = latest
        # loop outputs computed on the previous scan land now
        for tag, v in self.pending_writes.items():
            self.value[tag] = v
        self.pending_writes = {}

    def phase_alarms(self, t):
        for a in self.alarms:
            pv = self.value[a["tag"]]
            kind, lim, db = a["kind"], a["limit"], a.get("deadband", 0.0)
            high = kind in ("HI", "HIHI")
            raw = pv > lim if high else pv < lim
            if a["_latched"]:
                # asymmetric: clear only past the deadband
                still = pv >= lim - db if high else pv <= lim + db
                latched = still
            else:
                latched = raw

            if latched and not a["_latched"]:
                a["_since_true"] = t
                a["_since_false"] = None
            elif not latched and a["_latched"]:
                a["_since_false"] = t
                a["_since_true"] = None
            a["_latched"] = latched

            if latched:
                if a["_since_true"] is None:
                    a["_since_true"] = t
                # Defect #25: this read `t - _since_true >= on_delay_ms`, which fires on the FOURTH
                # scan of the condition for on_delay=300/scan=100 — one scan later than both the
                # spec's worked example and the docstring above. A scan-based timer accumulates one
                # scan period per scan it observes the condition true, so the Nth true scan has
                # accumulated N*scan_ms. fable5.1, opus5 and sonnet5 independently implemented that
                # reading and were all judged wrong by this line.
                if not a["_active"] and (t - a["_since_true"]) + self.scan >= a.get("on_delay_ms", 0):
                    a["_active"] = True
                    self.journal.append({"t_ms": t, "tag": a["tag"], "kind": kind,
                                         "event": "ACT", "priority": a.get("priority", 1)})
            else:
                if a["_since_false"] is None:
                    a["_since_false"] = t
                if a["_active"] and (t - a["_since_false"]) + self.scan >= a.get("off_delay_ms", 0):
                    a["_active"] = False
                    self.journal.append({"t_ms": t, "tag": a["tag"], "kind": kind,
                                         "event": "CLR", "priority": a.get("priority", 1)})

    def phase_loops(self, t):
        dt = self.scan / 1000.0
        for l in self.loops:
            pv = self.value[l["pv"]]
            e = l["sp"] - pv
            if l["_e_prev"] is None:
                l["_e_prev"] = e
            I_before = l["_I"]
            l["_I"] = I_before + l.get("ki", 0.0) * e * dt
            P = l.get("kp", 0.0) * e
            D = l.get("kd", 0.0) * (e - l["_e_prev"]) / dt
            raw = P + l["_I"] + D
            lo, hi = l.get("out_min", -1e30), l.get("out_max", 1e30)
            out = min(max(raw, lo), hi)
            if raw < lo or raw > hi:
                l["_I"] = I_before          # anti-windup: undo this scan's accumulation
            l["_e_prev"] = e
            self.loop_out[l["id"]].append({"t_ms": t, "out": out})
            if l.get("out"):
                self.pending_writes[l["out"]] = out

    def phase_historian(self, t):
        for tag in self.history:
            self.history[tag].append((t, self.value[tag]))

    # ---------------------------------------------------------------- queries

    def query(self, q):
        tag, f, to = q["tag"], q["from_ms"], q["to_ms"]
        pts = [(t, v) for (t, v) in self.history[tag] if f <= t <= to]
        if not pts:
            return None
        agg = q["agg"]
        if agg == "count":
            return len(pts)
        vals = [v for (_, v) in pts]
        if agg == "min":
            return min(vals)
        if agg == "max":
            return max(vals)
        if agg == "avg":
            return sum(vals) / len(vals)
        if agg == "twavg":
            num = den = 0.0
            for i, (t, v) in enumerate(pts):
                nxt = pts[i + 1][0] if i + 1 < len(pts) else to
                w = nxt - t
                num += v * w
                den += w
            return num / den if den > 0 else vals[0]
        raise SystemExit(f"ref_scada: unknown agg {agg!r}")

    def modbus(self):
        m = self.scen.get("modbus", {}).get("holding", {})
        if not m:
            return []
        size = max(m.values()) + 1
        regs = [0] * size
        for tag, addr in m.items():
            v = self.value[tag]
            if self.tags[tag].get("type") == "digital":
                regs[addr] = 1 if v else 0
            else:
                regs[addr] = max(0, min(65535, _round_half_away(float(v) * 10.0)))
        return regs

    # ---------------------------------------------------------------- driver

    def run(self):
        t = 0
        while t <= self.t_end:
            self.phase_input(t)
            self.phase_alarms(t)
            self.phase_loops(t)
            self.phase_historian(t)
            t += self.scan
        self.journal.sort(key=lambda e: (e["t_ms"], e["priority"], e["tag"], e["kind"]))
        return {"alarm_journal": self.journal,
                "loop_outputs": self.loop_out,
                "historian": [{"query": i, "value": self.query(q)}
                              for i, q in enumerate(self.scen.get("queries", []))],
                "modbus_registers": self.modbus()}


def run(scen):
    return Engine(scen).run()


def main():
    scen = json.loads(pathlib.Path(sys.argv[1]).read_text())
    pathlib.Path(sys.argv[2]).write_text(json.dumps(run(scen), indent=1))


if __name__ == "__main__":
    main()
