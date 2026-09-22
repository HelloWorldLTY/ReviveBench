#!/usr/bin/env python3
"""Rewrite a Yosys-written gate netlist into the primitive form the task spec allows.

Yosys cannot round-trip Verilog gate primitives: feeding it `and u (y, a, b);` lowers the
primitive into its own word-level `$and` cell, and `write_verilog` then emits `$and` instances
that neither Icarus nor the SAT solver can model. So the reference flow stops at Yosys's
bit-level `$_*_` cells and this pass converts them textually.

    $_NOT_  u (.A(a), .Y(y));            ->  not  u (y, a);
    $_AND_  u (.A(a), .B(b), .Y(y));     ->  and  u (y, a, b);
    $_MUX_  u (.A(a), .B(b), .S(s), .Y(y)) -> expanded to not/and/and/or with fresh wires
    $_DFF_P_ u (.C(c), .D(d), .Q(q));    ->  DFF  u (.Q(q), .D(d), .CLK(c));

usage: cellmap.py <in.v> <out.v>
"""
import re
import sys

TWO_IN = {"AND": "and", "OR": "or", "NAND": "nand", "NOR": "nor", "XOR": "xor", "XNOR": "xnor"}

CELL_RE = re.compile(r"\\?\$_([A-Z0-9_]+?)_\s+(\S+)\s*\(([^;]*?)\)\s*;", re.S)
CONN_RE = re.compile(r"\.(\w+)\s*\(\s*([^()]*?)\s*\)")


def convert(text):
    # Yosys keeps the original register name as an escaped identifier and appends the internal
    # name as a comment: `\$_DFF_P_  \q_reg[0]  /* _127_ */ (`. That comment sits between the
    # instance name and its port list, so strip comments before matching anything.
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    fresh = []
    counter = [0]

    def new_wire():
        counter[0] += 1
        name = f"_cmap_w{counter[0]}"
        fresh.append(name)
        return name

    def repl(m):
        kind, inst, conns = m.group(1), m.group(2), m.group(3)
        c = dict(CONN_RE.findall(conns))
        if kind in TWO_IN:
            prim = TWO_IN[kind]
            return f"{prim} {inst} ({c.get('Y')}, {c.get('A')}, {c.get('B')});"
        if kind == "NOT":
            return f"not {inst} ({c.get('Y')}, {c.get('A')});"
        if kind == "BUF":
            return f"buf {inst} ({c.get('Y')}, {c.get('A')});"
        if kind == "MUX":
            a, b, s, y = c.get("A"), c.get("B"), c.get("S"), c.get("Y")
            ns, t0, t1 = new_wire(), new_wire(), new_wire()
            return (f"not {inst}_n ({ns}, {s});\n"
                    f"  and {inst}_a0 ({t0}, {a}, {ns});\n"
                    f"  and {inst}_a1 ({t1}, {b}, {s});\n"
                    f"  or  {inst} ({y}, {t0}, {t1});")
        if kind.startswith("DFF"):
            return f"DFF {inst} (.Q({c.get('Q')}), .D({c.get('D')}), .CLK({c.get('C')}));"
        raise SystemExit(f"cellmap: unhandled cell type $_{kind}_ in instance {inst}")

    out = CELL_RE.sub(repl, text)
    if fresh:
        decls = "\n".join(f"  wire {w};" for w in fresh)
        # Declarations must precede first use. A gate instance naming an undeclared net makes
        # Verilog create that net implicitly, so declaring it afterwards is a redeclaration and
        # Icarus rejects the file; put the fresh wires right after the module header instead.
        out = re.sub(r"(?ms)^(module\b.*?;[ \t]*\n)", lambda m: m.group(1) + decls + "\n", out, count=1)
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    text = open(src).read()
    converted = convert(text)
    leftover = re.findall(r"\\?\$_[A-Z0-9_]+_", converted) + re.findall(r"\\?\$[a-z]+\s", converted)
    if leftover:
        raise SystemExit(f"cellmap: cells left unconverted: {sorted(set(leftover))[:6]}")
    open(dst, "w").write(converted)


if __name__ == "__main__":
    main()
