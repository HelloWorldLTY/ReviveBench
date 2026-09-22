#!/usr/bin/env python3
"""Reference IEC 61131-3 ST interpreter for generating expected traces (hidden). Usage: reference_plc.py prog.st stim.csv trace.csv cycle_ms"""
import re, sys, math
TOK = re.compile(r"\s+|\(\*.*?\*\)|//[^\n]*|(?P<time>T#[0-9a-zA-Z_.]+)|(?P<real>\d+\.\d+(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+)|(?P<int>\d+)|(?P<id>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>:=|<>|<=|>=|\.\.|[-+*/<>=(),;:.&])", re.S)
KW = {"PROGRAM","END_PROGRAM","FUNCTION_BLOCK","END_FUNCTION_BLOCK","FUNCTION","END_FUNCTION","VAR","VAR_INPUT","VAR_OUTPUT","END_VAR","IF","THEN","ELSIF","ELSE","END_IF","CASE","OF","END_CASE","FOR","TO","BY","DO","END_FOR","WHILE","END_WHILE","REPEAT","UNTIL","END_REPEAT","EXIT","RETURN","NOT","AND","OR","XOR","MOD","TRUE","FALSE"}
def parse_time(s):
    s = s[2:].lower(); ms = 0.0
    for v, u in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", s): ms += float(v) * {"ms": 1, "s": 1000, "m": 60000, "h": 3600000, "d": 86400000}[u]
    return int(round(ms))
def tokenize(src):
    out = []
    for m in TOK.finditer(src):
        if m.lastgroup is None: continue
        k, v = m.lastgroup, m.group(0)
        if k == "id" and v.upper() in KW: out.append(("kw", v.upper()))
        elif k == "id": out.append(("id", v))
        elif k == "time": out.append(("lit", ("TIME", parse_time(v))))
        elif k == "real": out.append(("lit", ("REAL", float(v))))
        elif k == "int": out.append(("lit", ("INT", int(v))))
        else: out.append(("op", v))
    return out
class P:
    def __init__(s, toks): s.t = toks; s.i = 0
    def peek(s, k=0): return s.t[s.i + k] if s.i + k < len(s.t) else ("eof", None)
    def next(s): tok = s.peek(); s.i += 1; return tok
    def accept(s, kind, val=None):
        tok = s.peek()
        if tok[0] == kind and (val is None or tok[1] == val): s.i += 1; return tok
        return None
    def expect(s, kind, val=None):
        tok = s.accept(kind, val)
        if tok is None: raise SyntaxError(f"expected {kind} {val} at {s.peek()} (#{s.i})")
        return tok
    def unit(s):
        pous = {}
        while s.peek()[0] != "eof":
            kind = s.expect("kw")[1]; name = s.expect("id")[1]; pou = {"kind": kind, "name": name, "vars": [], "body": []}
            if kind == "FUNCTION": s.expect("op", ":"); pou["ret"] = s.expect("id")[1]
            while s.peek()[1] in ("VAR", "VAR_INPUT", "VAR_OUTPUT"):
                sect = s.next()[1]
                while not s.accept("kw", "END_VAR"):
                    names = [s.expect("id")[1]]
                    while s.accept("op", ","): names.append(s.expect("id")[1])
                    s.expect("op", ":"); typ = s.expect("id")[1].upper(); init = None
                    if s.accept("op", ":="): init = s.expr()
                    s.expect("op", ";")
                    for n in names: pou["vars"].append((sect, n, typ, init))
            pou["body"] = s.stmts({"END_PROGRAM", "END_FUNCTION_BLOCK", "END_FUNCTION"}); s.next(); pous[name] = pou
        return pous
    def stmts(s, stop):
        out = []
        while s.peek()[1] not in stop and s.peek()[0] != "eof": out.append(s.stmt())
        return out
    def stmt(s):
        tok = s.peek()
        if tok == ("kw", "IF"):
            s.next(); branches = []; cond = s.expr(); s.expect("kw", "THEN"); body = s.stmts({"ELSIF", "ELSE", "END_IF"}); branches.append((cond, body)); els = []
            while s.accept("kw", "ELSIF"): c = s.expr(); s.expect("kw", "THEN"); branches.append((c, s.stmts({"ELSIF", "ELSE", "END_IF"})))
            if s.accept("kw", "ELSE"): els = s.stmts({"END_IF"})
            s.expect("kw", "END_IF"); s.accept("op", ";"); return ("if", branches, els)
        if tok == ("kw", "CASE"):
            s.next(); sel = s.expr(); s.expect("kw", "OF"); cases = []; els = []
            while not s.accept("kw", "END_CASE"):
                if s.accept("kw", "ELSE"): els = s.stmts({"END_CASE"}); continue
                vals = [s.caseval()]
                while s.accept("op", ","): vals.append(s.caseval())
                s.expect("op", ":"); cases.append((vals, s.stmts({"END_CASE", "ELSE"} | {None}, ) if False else s.casebody()))
            s.accept("op", ";"); return ("case", sel, cases, els)
        if tok == ("kw", "FOR"):
            s.next(); v = s.expect("id")[1]; s.expect("op", ":="); a = s.expr(); s.expect("kw", "TO"); b = s.expr(); st = ("lit", ("INT", 1))
            if s.accept("kw", "BY"): st = s.expr()
            s.expect("kw", "DO"); body = s.stmts({"END_FOR"}); s.next(); s.accept("op", ";"); return ("for", v, a, b, st, body)
        if tok == ("kw", "WHILE"):
            s.next(); c = s.expr(); s.expect("kw", "DO"); body = s.stmts({"END_WHILE"}); s.next(); s.accept("op", ";"); return ("while", c, body)
        if tok == ("kw", "REPEAT"):
            s.next(); body = s.stmts({"UNTIL"}); s.next(); c = s.expr(); s.expect("kw", "END_REPEAT"); s.accept("op", ";"); return ("repeat", body, c)
        if tok == ("kw", "EXIT"): s.next(); s.accept("op", ";"); return ("exit",)
        if tok == ("kw", "RETURN"): s.next(); s.accept("op", ";"); return ("return",)
        name = s.expect("id")[1]
        if s.accept("op", "("):
            args = []
            while not s.accept("op", ")"):
                pn = s.expect("id")[1]; s.expect("op", ":="); args.append((pn, s.expr())); s.accept("op", ",")
            s.expect("op", ";"); return ("call", name, args)
        path = [name]
        while s.accept("op", "."): path.append(s.expect("id")[1])
        s.expect("op", ":="); e = s.expr(); s.expect("op", ";"); return ("assign", path, e)
    def caseval(s):
        v = s.expr()
        if s.accept("op", ".."): return ("range", v, s.expr())
        return v
    def casebody(s):
        out = []
        while True:
            tok = s.peek()
            if tok[1] in ("END_CASE", "ELSE"): break
            # a new case label looks like: literal/ident ("," ...)* ":" — but "id :=" is an assignment
            if tok[0] in ("lit", "id"):
                j = s.i
                while s.t[j][0] in ("lit", "id") or s.t[j] == ("op", ",") or s.t[j] == ("op", "..") or (s.t[j][0] == "op" and s.t[j][1] == "-"): j += 1
                if s.t[j] == ("op", ":"): break
            out.append(s.stmt())
        return out
    def expr(s): return s.binop(0)
    LEVELS = [({"OR"}, "kw"), ({"XOR"}, "kw"), ({"AND", "&"}, None), ({"=", "<>"}, "op"), ({"<", "<=", ">", ">="}, "op"), ({"+", "-"}, "op"), ({"*", "/", "MOD"}, None)]
    def binop(s, lvl):
        if lvl == len(s.LEVELS): return s.unary()
        ops, kind = s.LEVELS[lvl]; left = s.binop(lvl + 1)
        while s.peek()[1] in ops and (kind is None or s.peek()[0] == kind):
            op = s.next()[1]; right = s.binop(lvl + 1); left = ("bin", op, left, right)
        return left
    def unary(s):
        if s.accept("kw", "NOT"): return ("not", s.unary())
        if s.accept("op", "-"): return ("neg", s.unary())
        return s.primary()
    def primary(s):
        tok = s.next()
        if tok[0] == "lit": return ("lit", tok[1])
        if tok == ("kw", "TRUE"): return ("lit", ("BOOL", True))
        if tok == ("kw", "FALSE"): return ("lit", ("BOOL", False))
        if tok == ("op", "("): e = s.expr(); s.expect("op", ")"); return e
        if tok[0] == "id":
            if s.accept("op", "("):
                args = []
                while not s.accept("op", ")"): args.append(s.expr()); s.accept("op", ",")
                return ("fn", tok[1].upper(), args)
            path = [tok[1]]
            while s.accept("op", "."): path.append(s.expect("id")[1])
            return ("var", path)
        raise SyntaxError(f"unexpected {tok}")
DEFAULT = {"BOOL": False, "INT": 0, "DINT": 0, "REAL": 0.0, "TIME": 0}
def wrap(v, typ):
    if typ == "INT": v = int(v); return ((v + 32768) % 65536) - 32768
    if typ == "DINT": v = int(v); return ((v + 2**31) % 2**32) - 2**31
    if typ == "REAL": return float(v)
    if typ == "BOOL": return bool(v)
    return int(v)
class StdFB:
    def __init__(s, kind): s.kind = kind; s.Q = False; s.ET = 0; s.CV = 0; s.Q1 = False; s.prev = False; s.start = None; s.run = False
    def call(s, rt, a):
        t = rt.now; k = s.kind
        if k == "TON":
            IN, PT = a.get("IN", False), a.get("PT", 0)
            if not IN: s.start = None; s.Q = False; s.ET = 0
            else:
                if s.start is None: s.start = t
                s.ET = min(t - s.start, PT); s.Q = (t - s.start) >= PT
        elif k == "TOF":
            IN, PT = a.get("IN", False), a.get("PT", 0)
            if IN: s.Q = True; s.start = None; s.ET = 0
            else:
                if s.Q and s.start is None: s.start = t
                if s.start is not None:
                    s.ET = min(t - s.start, PT); s.Q = (t - s.start) < PT
        elif k == "TP":
            IN, PT = a.get("IN", False), a.get("PT", 0)
            if s.start is not None and (t - s.start) >= PT: s.Q = False; s.ET = PT
            if IN and not s.prev and s.start is None: s.start = t
            if s.start is not None and (t - s.start) < PT: s.Q = True; s.ET = t - s.start
            if s.start is not None and (t - s.start) >= PT and not IN: s.start = None; s.ET = 0
            s.prev = IN
        elif k == "CTU":
            CU, R, PV = a.get("CU", False), a.get("R", False), a.get("PV", 0)
            if R: s.CV = 0
            elif CU and not s.prev and s.CV < 32767: s.CV += 1
            s.prev = CU; s.Q = s.CV >= PV
        elif k == "CTD":
            CD, LD, PV = a.get("CD", False), a.get("LD", False), a.get("PV", 0)
            if LD: s.CV = PV
            elif CD and not s.prev and s.CV > -32768: s.CV -= 1
            s.prev = CD; s.Q = s.CV <= 0
        elif k == "R_TRIG": CLK = a.get("CLK", False); s.Q = CLK and not s.prev; s.prev = CLK
        elif k == "F_TRIG": CLK = a.get("CLK", False); s.Q = (not CLK) and s.prev; s.prev = CLK
        elif k == "SR": S1, R = a.get("S1", False), a.get("R", False); s.Q1 = S1 or (s.Q1 and not R)
        elif k == "RS": S, R1 = a.get("S", False), a.get("R1", False); s.Q1 = (not R1) and (S or s.Q1)
    def get(s, n): return getattr(s, n)
class Exit(Exception): pass
class Ret(Exception): pass
class Inst:
    def __init__(s, rt, pou):
        s.rt, s.pou, s.vals, s.types = rt, pou, {}, {}
        for sect, n, typ, init in pou["vars"]:
            s.types[n] = typ
            if typ in DEFAULT: s.vals[n] = rt.eval(init, s) if init is not None else DEFAULT[typ]
            elif typ in ("TON", "TOF", "TP", "CTU", "CTD", "R_TRIG", "F_TRIG", "SR", "RS"): s.vals[n] = StdFB(typ)
            else: s.vals[n] = Inst(rt, rt.pou(typ))
        if pou["kind"] == "FUNCTION": s.types[pou["name"]] = pou["ret"].upper(); s.vals[pou["name"]] = DEFAULT[pou["ret"].upper()]
class RT:
    def __init__(s, pous): s.pous = pous; s.now = 0; s.upper = {k.upper(): v for k, v in pous.items()}
    def pou(s, name): return s.upper[name.upper()]
    def get(s, inst, path):
        v = inst.vals[path[0]]
        for p in path[1:]: v = v.get(p) if isinstance(v, StdFB) else v.vals[p]
        return v
    def eval(s, e, inst):
        k = e[0]
        if k == "lit": return e[1][1]
        if k == "var": return s.get(inst, e[1])
        if k == "not": return not s.eval(e[1], inst)
        if k == "neg": return -s.eval(e[1], inst)
        if k == "bin":
            op = e[1]; a = s.eval(e[2], inst)
            if op == "AND" or op == "&": return bool(a) and bool(s.eval(e[3], inst))
            if op == "OR": return bool(a) or bool(s.eval(e[3], inst))
            b = s.eval(e[3], inst)
            if op == "XOR": return bool(a) != bool(b)
            if op == "+": return a + b
            if op == "-": return a - b
            if op == "*": return a * b
            if op == "/": return a / b if isinstance(a, float) or isinstance(b, float) else int(a / b)
            if op == "MOD": return int(math.fmod(a, b))
            if op == "=": return a == b
            if op == "<>": return a != b
            if op == "<": return a < b
            if op == "<=": return a <= b
            if op == ">": return a > b
            if op == ">=": return a >= b
        if k == "fn":
            f = e[1]; a = [s.eval(x, inst) for x in e[2]]
            if f == "ABS": return abs(a[0])
            if f == "MIN": return min(a)
            if f == "MAX": return max(a)
            if f == "LIMIT": return min(max(a[1], a[0]), a[2])
            if f == "SEL": return a[2] if a[0] else a[1]
            if f == "INT_TO_REAL": return float(a[0])
            if f == "REAL_TO_INT": return int(math.floor(a[0] + 0.5)) if a[0] >= 0 else -int(math.floor(-a[0] + 0.5))
            if f == "TIME_TO_DINT": return int(a[0])
            if f == "DINT_TO_TIME": return int(a[0])
            if f in s.upper:  # user function
                pou = s.pou(f); fi = Inst(s, pou); ins = [n for sect, n, _, _ in pou["vars"] if sect == "VAR_INPUT"]
                for n, v in zip(ins, a): fi.vals[n] = wrap(v, fi.types[n])
                try: s.run(pou["body"], fi)
                except Ret: pass
                return fi.vals[pou["name"]]
            raise NameError(f)
        raise ValueError(e)
    def assign(s, inst, path, v):
        if len(path) == 1: inst.vals[path[0]] = wrap(v, inst.types[path[0]])
        else:
            sub = s.get(inst, path[:-1]); sub.vals[path[-1]] = wrap(v, sub.types[path[-1]])
    def run(s, body, inst):
        for st in body:
            k = st[0]
            if k == "assign": s.assign(inst, st[1], s.eval(st[2], inst))
            elif k == "call":
                fb = inst.vals[st[1]]; args = {n: s.eval(e, inst) for n, e in st[2]}
                if isinstance(fb, StdFB): fb.call(s, args)
                else:
                    for n, v in args.items(): fb.vals[n] = wrap(v, fb.types[n])
                    try: s.run(fb.pou["body"], fb)
                    except Ret: pass
            elif k == "if":
                for c, b in st[1]:
                    if s.eval(c, inst): s.run(b, inst); break
                else: s.run(st[2], inst)
            elif k == "case":
                v = s.eval(st[1], inst); hit = False
                for vals, b in st[2]:
                    for cv in vals:
                        m = (s.eval(cv[1], inst) <= v <= s.eval(cv[2], inst)) if cv[0] == "range" else (s.eval(cv, inst) == v)
                        if m: hit = True; break
                    if hit: s.run(b, inst); break
                if not hit: s.run(st[3], inst)
            elif k == "for":
                a, b, step = s.eval(st[2], inst), s.eval(st[3], inst), s.eval(st[4], inst); i = a
                try:
                    while (i <= b) if step > 0 else (i >= b):
                        s.assign(inst, [st[1]], i); s.run(st[5], inst); i += step
                except Exit: pass
            elif k == "while":
                try:
                    while s.eval(st[1], inst): s.run(st[2], inst)
                except Exit: pass
            elif k == "repeat":
                try:
                    while True:
                        s.run(st[1], inst)
                        if s.eval(st[2], inst): break
                except Exit: pass
            elif k == "exit": raise Exit()
            elif k == "return": raise Ret()
def main(prog, stim, trace, cycle):
    pous = P(tokenize(open(prog).read())).unit(); rt = RT(pous)
    main_pou = next(p for p in pous.values() if p["kind"] == "PROGRAM"); inst = Inst(rt, main_pou)
    ins = [n for sect, n, _, _ in main_pou["vars"] if sect == "VAR_INPUT"]; outs = [n for sect, n, _, _ in main_pou["vars"] if sect == "VAR_OUTPUT"]
    lines = [l.strip() for l in open(stim) if l.strip()]; hdr = lines[0].split(",")
    with open(trace, "w") as f:
        f.write(",".join(outs) + "\n")
        for k, l in enumerate(lines[1:]):
            rt.now = k * int(cycle); row = dict(zip(hdr, l.split(",")))
            for n in ins:
                t = inst.types[n]; raw = row[n]
                inst.vals[n] = wrap(float(raw) if t == "REAL" else int(float(raw)), t) if t != "BOOL" else raw.strip() in ("1", "TRUE", "true")
            rt.run(main_pou["body"], inst)
            f.write(",".join(("1" if inst.vals[n] else "0") if inst.types[n] == "BOOL" else (repr(float(inst.vals[n])) if inst.types[n] == "REAL" else str(int(inst.vals[n]))) for n in outs) + "\n")
if __name__ == "__main__": main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
