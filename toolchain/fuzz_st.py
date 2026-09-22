#!/usr/bin/env python3
"""Random IEC 61131-3 Structured Text program generator, for differential testing.

Programs are type-correct and terminating by construction. Each generated case is a
(program, stimulus) pair; the expected output trace comes from the reference interpreter,
so the number of assertions available is unbounded.

usage:
  fuzz_st.py gen  --out <dir> --n 200 [--seed 7] [--scans 120] [--complexity 1..3]
  fuzz_st.py ref  --dir <dir>                       # fill in expected traces (reference interpreter)
  fuzz_st.py diff --dir <dir> --cmd "<runner> {prog} {stim} {trace} {cycle}"
"""
import argparse
import json
import pathlib
import random
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REF = HERE.parents[0] / "tasks" / "plc_iec61131" / "hidden" / "reference_plc.py"
CYCLE = 10

FBS = {
    "TON": (["IN", "PT"], ["Q", "ET"]),
    "TOF": (["IN", "PT"], ["Q", "ET"]),
    "TP": (["IN", "PT"], ["Q", "ET"]),
    "CTU": (["CU", "R", "PV"], ["Q", "CV"]),
    "CTD": (["CD", "LD", "PV"], ["Q", "CV"]),
    "R_TRIG": (["CLK"], ["Q"]),
    "F_TRIG": (["CLK"], ["Q"]),
    "SR": (["S1", "R"], ["Q1"]),
    "RS": (["S", "R1"], ["Q1"]),
}


class Gen:
    def __init__(self, rng, complexity=2):
        self.r = rng
        self.c = complexity
        self.bools, self.ints, self.reals, self.times = [], [], [], []
        self.fbs = {}          # name -> kind
        self.active_loops = []  # loop control variables currently in scope
        # IEC 61131-3 leaves the value of a FOR control variable after the loop implementation-defined,
        # so loop variables are reserved: never read in an expression, never assigned outside their loop.
        self.loop_vars = set()
        self.inputs = set()      # VAR_INPUT is read-only in IEC 61131-3: never an assignment target
        self.out_bools, self.out_ints, self.out_reals, self.out_times = [], [], [], []

    # ---------- declarations ----------
    def declare(self):
        r = self.r
        n_in_b = r.randint(1, 3)
        n_in_i = r.randint(0, 2)
        n_in_r = r.randint(0, 1) if self.c >= 2 else 0
        ins = []
        for i in range(n_in_b):
            v = f"bi{i}"; self.bools.append(v); self.inputs.add(v); ins.append((v, "BOOL"))
        for i in range(n_in_i):
            v = f"ii{i}"; self.ints.append(v); self.inputs.add(v); ins.append((v, "INT"))
        for i in range(n_in_r):
            v = f"ri{i}"; self.reals.append(v); self.inputs.add(v); ins.append((v, "REAL"))
        outs = []
        for i in range(r.randint(1, 3)):
            v = f"bo{i}"; self.bools.append(v); self.out_bools.append(v); outs.append((v, "BOOL"))
        for i in range(r.randint(1, 2)):
            v = f"io{i}"; self.ints.append(v); self.out_ints.append(v); outs.append((v, "INT"))
        if self.c >= 2:
            for i in range(r.randint(0, 1)):
                v = f"ro{i}"; self.reals.append(v); self.out_reals.append(v); outs.append((v, "REAL"))
            for i in range(r.randint(0, 1)):
                v = f"to{i}"; self.times.append(v); self.out_times.append(v); outs.append((v, "TIME"))
        loc = []
        for i in range(r.randint(1, 3)):
            v = f"bl{i}"; self.bools.append(v); loc.append((v, "BOOL"))
        for i in range(r.randint(1, 2)):
            v = f"il{i}"; self.ints.append(v); self.loop_vars.add(v); loc.append((v, "INT"))
        for i in range(r.randint(1, 2 + self.c)):
            kind = r.choice(list(FBS))
            name = f"fb{i}"; self.fbs[name] = kind; loc.append((name, kind))
        return ins, outs, loc

    # ---------- expressions ----------
    def bexpr(self, d=0):
        r = self.r
        opts = ["var", "cmp", "not", "and", "or", "fbout", "lit"]
        k = r.choice(opts if d < self.c else ["var", "lit", "fbout"])
        if k == "var" and self.bools:
            return r.choice(self.bools)
        if k == "lit":
            return r.choice(["TRUE", "FALSE"])
        if k == "not":
            return f"NOT ({self.bexpr(d + 1)})"
        if k in ("and", "or"):
            return f"({self.bexpr(d + 1)} {'AND' if k == 'and' else 'OR'} {self.bexpr(d + 1)})"
        if k == "cmp" and self.ints:
            op = r.choice(["=", "<>", "<", "<=", ">", ">="])
            return f"({self.iexpr(d + 1)} {op} {self.iexpr(d + 1)})"
        if k == "fbout" and self.fbs:
            name = r.choice(list(self.fbs))
            kind = self.fbs[name]
            bo = [o for o in FBS[kind][1] if o in ("Q", "Q1")]
            if bo:
                return f"{name}.{r.choice(bo)}"
        return r.choice(self.bools) if self.bools else "TRUE"

    def iexpr(self, d=0):
        r = self.r
        k = r.choice(["var", "lit", "add", "mul", "fn", "fbcv"] if d < self.c else ["var", "lit"])
        readable = [v for v in self.ints if v not in self.loop_vars]
        if k == "var" and readable:
            return r.choice(readable)
        if k == "lit":
            return str(r.randint(-50, 200))
        if k == "add":
            return f"({self.iexpr(d + 1)} {r.choice('+-')} {self.iexpr(d + 1)})"
        if k == "mul":
            # clamp the operand so the product cannot overflow INT at any nesting depth
            return f"(LIMIT(-1000, {self.iexpr(d + 1)}, 1000) * {r.randint(2, 4)})"
        if k == "fn":
            f = r.choice(["ABS", "MIN", "MAX", "LIMIT"])
            if f == "ABS":
                return f"ABS({self.iexpr(d + 1)})"
            if f == "LIMIT":
                return f"LIMIT(0, {self.iexpr(d + 1)}, {r.randint(10, 100)})"
            return f"{f}({self.iexpr(d + 1)}, {self.iexpr(d + 1)})"
        if k == "fbcv" and self.fbs:
            cands = [n for n, kk in self.fbs.items() if "CV" in FBS[kk][1]]
            if cands:
                return f"{r.choice(cands)}.CV"
        return r.choice(readable) if readable else "0"

    def rexpr(self, d=0):
        r = self.r
        if not self.reals or d >= self.c:
            return f"{r.uniform(-20, 20):.3f}"
        k = r.choice(["var", "lit", "add", "int2real"])
        if k == "var":
            return r.choice(self.reals)
        if k == "lit":
            return f"{r.uniform(-20, 20):.3f}"
        if k == "int2real":
            return f"INT_TO_REAL({self.iexpr(d + 1)})"
        return f"({self.rexpr(d + 1)} {r.choice('+-*')} {self.rexpr(d + 1)})"

    def texpr(self):
        r = self.r
        return r.choice([f"T#{r.randint(1, 900)}ms", f"T#{r.randint(1, 3)}s", f"T#{r.randint(1, 2)}s{r.randint(1, 500)}ms"])

    # ---------- statements ----------
    def safe_bool_assign(self, ind):
        tgt = [v for v in self.bools if v not in self.inputs] or self.bools
        return f"{ind}{self.r.choice(tgt)} := {self.bexpr()};"

    def stmt(self, d=0):
        r = self.r
        kinds = ["assign_b", "assign_i", "fbcall", "if"]
        if self.c >= 2:
            kinds += ["case", "for", "assign_r", "assign_t"]
        if self.c >= 3:
            kinds += ["while"]
        k = r.choice(kinds if d < 2 else ["assign_b", "assign_i", "fbcall"])
        ind = "  " * d
        if k == "assign_b":
            return self.safe_bool_assign(ind)
        if k == "assign_i":
            tgt = [v for v in self.ints if v not in self.loop_vars and v not in self.inputs]
            if not tgt:
                return self.safe_bool_assign(ind)
            # IEC 61131-3 leaves INT overflow implementation-dependent (wrap per operation vs per
            # assignment), so keep every accumulator small enough that intermediates cannot overflow.
            return f"{ind}{r.choice(tgt)} := LIMIT(-4000, {self.iexpr()}, 4000);"
        if k == "assign_r" and [v for v in self.reals if v not in self.inputs]:
            return f"{ind}{r.choice([v for v in self.reals if v not in self.inputs])} := {self.rexpr()};"
        if k == "assign_t" and self.times:
            return f"{ind}{r.choice(self.times)} := {self.texpr()};"
        if k == "fbcall" and self.fbs:
            name = r.choice(list(self.fbs))
            kind = self.fbs[name]
            args = []
            for p in FBS[kind][0]:
                if p == "PT":
                    args.append(f"PT := {self.texpr()}")
                elif p == "PV":
                    args.append(f"PV := {r.randint(1, 8)}")
                else:
                    args.append(f"{p} := {self.bexpr()}")
            return f"{ind}{name}({', '.join(args)});"
        if k == "if":
            body = "\n".join(self.stmt(d + 1) for _ in range(r.randint(1, 2)))
            s = f"{ind}IF {self.bexpr()} THEN\n{body}\n"
            if r.random() < 0.4:
                s += f"{ind}ELSIF {self.bexpr()} THEN\n" + "\n".join(self.stmt(d + 1) for _ in range(1)) + "\n"
            if r.random() < 0.5:
                s += f"{ind}ELSE\n" + "\n".join(self.stmt(d + 1) for _ in range(1)) + "\n"
            return s + f"{ind}END_IF;"
        if k == "case" and [v for v in self.ints if v not in self.loop_vars]:
            sel = r.choice([v for v in self.ints if v not in self.loop_vars])
            arms = []
            used = r.sample(range(0, 6), r.randint(2, 3))
            for v in used:
                arms.append(f"{ind}  {v}:\n" + "\n".join(self.stmt(d + 2) for _ in range(1)))
            els = f"{ind}  ELSE\n" + "\n".join(self.stmt(d + 2) for _ in range(1))
            return f"{ind}CASE {sel} OF\n" + "\n".join(arms) + "\n" + els + f"\n{ind}END_CASE;"
        if k == "for" and self.ints:
            free = [x for x in self.loop_vars if x not in self.active_loops]
            if not free:
                return self.safe_bool_assign(ind)
            v = r.choice(sorted(free))
            self.active_loops.append(v)
            body = "\n".join(self.stmt(d + 1) for _ in range(1))
            self.active_loops.pop()
            return f"{ind}FOR {v} := 1 TO {r.randint(2, 5)} DO\n{body}\n{ind}END_FOR;"
        if k == "while" and self.loop_vars:
            free = [x for x in self.loop_vars if x not in self.active_loops]
            if not free:
                return self.safe_bool_assign(ind)
            v = r.choice(sorted(free)); self.active_loops.append(v)
            body = "\n".join(self.stmt(d + 1) for _ in range(1))
            out = (f"{ind}{v} := 0;\n{ind}WHILE {v} < {r.randint(2, 4)} DO\n"
                   f"{body}\n{ind}  {v} := {v} + 1;\n{ind}END_WHILE;")
            self.active_loops.pop()
            return out
        return self.safe_bool_assign(ind)

    def program(self, name):
        ins, outs, loc = self.declare()
        body = "\n".join(self.stmt() for _ in range(self.r.randint(3, 4 + self.c)))
        def sec(kw, items):
            if not items:
                return ""
            lines = "\n".join(f"  {v} : {t};" for v, t in items)
            return f"{kw}\n{lines}\nEND_VAR\n"
        src = (f"PROGRAM {name}\n" + sec("VAR_INPUT", ins) + sec("VAR_OUTPUT", outs) + sec("VAR", loc) +
               body + "\nEND_PROGRAM\n")
        return src, ins, outs


def gen_stimulus(rng, ins, scans):
    hdr = [v for v, _ in ins]
    rows = [hdr]
    state = {}
    for k in range(scans):
        row = []
        for v, t in ins:
            if t == "BOOL":
                p = state.setdefault(v, 0)
                if rng.random() < 0.18:
                    p = 1 - p
                state[v] = p
                row.append(p)
            elif t == "INT":
                row.append(rng.randint(-20, 60))
            else:
                row.append(round(rng.uniform(-30, 30), 3))
        rows.append(row)
    return "\n".join(",".join(str(x) for x in r) for r in rows) + "\n"


def cmd_gen(a):
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    made = 0
    for i in range(a.n):
        g = Gen(random.Random(rng.randrange(1 << 30)), complexity=a.complexity)
        name = f"P{i:04d}"
        src, ins, outs = g.program(name)
        d = out / name
        d.mkdir(exist_ok=True)
        (d / "prog.st").write_text(src)
        (d / "stim.csv").write_text(gen_stimulus(random.Random(rng.randrange(1 << 30)), ins, a.scans))
        made += 1
    print(f"generated {made} cases in {out}")


def cmd_ref(a):
    d = pathlib.Path(a.dir)
    ok = bad = 0
    for case in sorted(d.iterdir()):
        if not (case / "prog.st").exists():
            continue
        tr = case / "expected.csv"
        p = subprocess.run([sys.executable, str(REF), str(case / "prog.st"), str(case / "stim.csv"),
                            str(tr), str(CYCLE)], capture_output=True, text=True, timeout=300)
        if p.returncode == 0 and tr.exists() and len(tr.read_text().splitlines()) > 1:
            ok += 1
        else:
            bad += 1
            (case / "ref_error.txt").write_text((p.stdout + p.stderr)[-400:])
    print(f"reference traces: {ok} ok, {bad} failed (failures are generator bugs, cases dropped)")


def read_trace(p):
    lines = [l.strip() for l in pathlib.Path(p).read_text().splitlines() if l.strip()]
    return lines[0].split(","), [l.split(",") for l in lines[1:]]


def same(a, b):
    try:
        fa, fb = float(a), float(b)
    except Exception:
        return a.strip() == b.strip()
    if "." in a or "." in b or "e" in a.lower() or "e" in b.lower():
        return abs(fa - fb) <= 1e-6 * max(1.0, abs(fb))
    return fa == fb


def cmd_diff(a):
    d = pathlib.Path(a.dir)
    tmp = pathlib.Path(tempfile.mkdtemp())
    total = passed = 0
    mismatches = []
    for case in sorted(d.iterdir()):
        exp = case / "expected.csv"
        if not exp.exists():
            continue
        total += 1
        got = tmp / f"{case.name}.csv"
        cmd = a.cmd.format(prog=case / "prog.st", stim=case / "stim.csv", trace=got, cycle=CYCLE)
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=a.timeout)
        except subprocess.TimeoutExpired:
            mismatches.append({"case": case.name, "why": f"timeout >{a.timeout}s (hang)"})
            continue
        if not got.exists():
            mismatches.append({"case": case.name, "why": "no trace", "detail": (r.stdout + r.stderr)[-200:]})
            continue
        eh, er = read_trace(exp)
        gh, gr = read_trace(got)
        col = {h.strip(): i for i, h in enumerate(gh)}
        bad = None
        for k, row in enumerate(er):
            grow = gr[k] if k < len(gr) else []
            for j, h in enumerate(eh):
                v = grow[col[h]] if h in col and col[h] < len(grow) else "MISSING"
                if not same(v, row[j]):
                    bad = f"scan {k} {h}: got {v} want {row[j]}"
                    break
            if bad:
                break
        if bad is None and len(gr) >= len(er):
            passed += 1
        else:
            mismatches.append({"case": case.name, "why": bad or "short trace"})
    res = {"total": total, "passed": passed, "rate": round(passed / max(total, 1), 4),
           "mismatches": mismatches[:40]}
    print(json.dumps(res, ensure_ascii=False, indent=1)[:2000])
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen"); g.add_argument("--out", required=True); g.add_argument("--n", type=int, default=100)
    g.add_argument("--seed", type=int, default=7); g.add_argument("--scans", type=int, default=120)
    g.add_argument("--complexity", type=int, default=2); g.set_defaults(f=cmd_gen)
    r = sub.add_parser("ref"); r.add_argument("--dir", required=True); r.set_defaults(f=cmd_ref)
    df = sub.add_parser("diff"); df.add_argument("--dir", required=True); df.add_argument("--cmd", required=True)
    df.add_argument("--timeout", type=int, default=120); df.add_argument("--out", default=None); df.set_defaults(f=cmd_diff)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
