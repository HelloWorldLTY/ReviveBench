#!/usr/bin/env python3
"""Data rows for Table 1 (tab:matrix) of the paper, from the matrix.csv that harness/build_matrix.py writes.

tables.tex, like matrix.csv, used to be produced ad hoc with no script kept; that is how twelve wrong
scores reached the paper.
This script emits only the part the data decides (one row per engine plus the totals row); the header
and caption stay hand-written in tables.tex, because they describe the experimental conditions.

Self-check: --check regenerates the rows for the current models and requires them to match the rows
in tables.tex character for character.
"""
import csv, re, sys, argparse

ROWS = [("stats_nist", "Statistics engine", "SAS, SPSS"),
        ("spice_ngspice", "Circuit simulator", "HSPICE"),
        ("plc_iec61131", "PLC runtime", "TIA Portal"),
        ("fem_nafems", "FE solver", "Nastran"),
        ("cad2d_dxf", "2D CAD kernel", "AutoCAD"),
        ("synth_verilog", "Logic synthesiser", "Design Compiler"),
        ("cad3d_brep", "3D solid modeller", "Parasolid"),
        ("erp_ledger", "ERP core", "SAP S/4HANA"),
        ("place_route", "Place \\& route", "Innovus"),
        ("cfd_solver", "CFD / CAE", "Fluent"),
        ("scada_dcs", "SCADA/DCS runtime", "WinCC"),
        ("mes_exec", "MES", "SAP ME"),
        ("plm_bom", "PLM / BOM", "Teamcenter")]
BASE = ["fable5.1", "opus5", "sonnet5", "haiku4.5", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra"]


def tex_cell(v):
    if not v or v == "INFRA":
        # Only infrastructure failures, no usable run: not a model result, so no tick or cross
        return "\\textemdash"
    verdict, frac = v.split()
    return "%s\\,\\scriptsize %s" % ("\\cmark" if verdict == "PASS" else "\\xmark", frac)


def rows(matrix, models):
    M = {r["task"]: r for r in csv.DictReader(open(matrix))}
    out = []
    for task, name, analogue in ROWS:
        out.append(" & ".join([name, analogue] + [tex_cell(M[task].get(m, "")) for m in models]) + " \\\\")
    total = []
    for m in models:
        n = sum(1 for task, _, _ in ROWS if (M[task].get(m) or "").startswith("PASS"))
        total.append("\\textbf{%d/%d}" % (n, len(ROWS)))
    out.append("\\textbf{Engines passed} & & " + " & ".join(total) + " \\\\")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="results/package/matrix.csv")
    ap.add_argument("--models", default=",".join(BASE))
    ap.add_argument("--check", metavar="TABLES_TEX")
    a = ap.parse_args()
    gen = rows(a.matrix, a.models.split(","))
    if not a.check:
        print("\n".join(gen)); return
    text = open(a.check).read()
    # Compare inside the tab:matrix table only: the effort-ablation table in the same file also has
    # "2D CAD kernel" and "ERP core" rows
    lab = text.index("\\label{tab:matrix}")
    beg = text.rindex("\\begin{table}", 0, lab)
    end = text.index("\\end{table}", lab)
    have = text[beg:end].split("\n")
    bad = 0
    for g in gen:
        key = g.split(" & ")[0]
        cur = [l for l in have if l.split(" & ")[0] == key]
        if len(cur) != 1:
            print("missing or not unique: %s (%d)" % (key, len(cur))); bad += 1; continue
        if cur[0].rstrip() != g:
            print("differs: %s\n  shipped:   %s\n  generated: %s" % (key, cur[0], g)); bad += 1
    print("self-check %s: %d rows compared, %d differ" % ("passed" if bad == 0 else "FAILED", len(gen), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
