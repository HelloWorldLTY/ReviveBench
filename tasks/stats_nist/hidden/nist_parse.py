"""Parse NIST StRD .dat files (LLS polynomial/linear, NLS, ANOVA one-way) into a task dict."""
import re, pathlib

def _nums(s):
    return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)]

def parse(path):
    t = pathlib.Path(path).read_text().splitlines()
    name = pathlib.Path(path).stem
    diff = next((l.strip().split()[0] for l in t if "Level of Difficulty" in l), "Average")
    proc = next((l for l in t if l.startswith("Procedure:")), "")
    # data block: from the "Data:" header line at ~60 to the end
    di = max(i for i, l in enumerate(t) if l.startswith("Data:"))
    header = t[di].split(":", 1)[1].split()
    rows = [_nums(l) for l in t[di + 1:] if _nums(l)]
    d = {"name": name, "difficulty": diff, "columns": header, "rows": rows}
    if "Nonlinear" in proc:
        d["kind"] = "NLS"
        mi = next(i for i, l in enumerate(t) if re.search(r"^\s*(log\[y\]|y)\s*=", l))
        d["log_response"] = bool(re.search(r"^\s*log\[y\]", t[mi]))
        model = []
        for l in t[mi:]:
            if not l.strip(): break
            model.append(l.strip())
        m = " ".join(model)
        m = re.sub(r"\+\s*e\s*$", "", m).strip()
        m = m.split("=", 1)[1].strip()
        m = m.replace("[", "(").replace("]", ")").replace("**", "^")
        d["model"] = m
        d["params"], d["start1"], d["start2"], d["cert"], d["cert_sd"] = [], [], [], [], []
        for l in t:
            mm = re.match(r"\s*(b\d+)\s*=\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", l)
            if mm:
                d["params"].append(mm.group(1)); d["start1"].append(float(mm.group(2))); d["start2"].append(float(mm.group(3)))
                d["cert"].append(float(mm.group(4))); d["cert_sd"].append(float(mm.group(5)))
        d["cert_rss"] = _nums(next(l for l in t if "Residual Sum of Squares" in l))[0]
        d["cert_rsd"] = _nums(next(l for l in t if "Residual Standard Deviation" in l))[0]
    elif "Analysis of Variance" in proc or "ANOVA" in proc.upper():
        d["kind"] = "ANOVA"
        bl = next(l for l in t if l.startswith("Between")); wl = next(l for l in t if l.startswith("Within"))
        b = _nums(bl.split(None, 2)[2] if False else re.sub(r"^Between\s+\S+", "", bl)); w = _nums(re.sub(r"^Within\s+\S+", "", wl))
        d["cert"] = {"between_df": b[0], "between_ss": b[1], "between_ms": b[2], "F": b[3], "within_df": w[0], "within_ss": w[1], "within_ms": w[2]}
        d["cert"]["r2"] = _nums(next(l for l in t if "Certified R-Squared" in l))[0]
        i = next(i for i, l in enumerate(t) if "Certified Residual" in l); d["cert"]["rsd"] = _nums(t[i + 1])[0]
    else:
        d["kind"] = "LLS"
        ml = next(l for l in t if re.search(r"^\s*y\s*=", l)).strip()
        d["model_text"] = ml
        npar = int(re.search(r"(\d+)\s+Parameters?\s*\(", next(l for l in t if re.search(r"\d+\s+Parameters?\s*\(", l))).group(1))
        d["intercept"] = "B0" in ml
        nx = len(header) - 1
        if nx == 1:  # polynomial in x of degree npar-1 (or npar if no intercept)
            d["degree"] = npar - 1 if d["intercept"] else npar
        else:
            d["degree"] = 1
        d["cert"], d["cert_sd"] = [], []
        for l in t:
            mm = re.match(r"\s*B(\d+)\s+(\S+)\s+(\S+)\s*$", l)
            if mm: d["cert"].append(float(mm.group(2))); d["cert_sd"].append(float(mm.group(3)))
        i = next(i for i, l in enumerate(t) if l.strip() == "Residual")
        d["cert_rsd"] = _nums(t[i + 1])[0]
        d["cert_r2"] = _nums(next(l for l in t if l.strip().startswith("R-Squared")))[0]
    return d

def to_syntax(d):
    """Build the data CSV and the SPSS-like syntax for one dataset."""
    cols = list(d["columns"]); rows = d["rows"]
    if d.get("log_response"):
        import math
        cols = ["logy"] + cols[1:]; rows = [[math.log(r[0])] + r[1:] for r in rows]
    csv = ",".join(cols) + "\n" + "\n".join(",".join(repr(v) for v in r) for r in rows) + "\n"
    if d["kind"] == "LLS":
        if len(cols) == 2:
            terms = " ".join(f"x^{k}" if k > 1 else "x" for k in range(1, d["degree"] + 1))
        else:
            terms = " ".join(cols[1:])
        origin = "/ORIGIN" if not d["intercept"] else "/NOORIGIN"
        syn = f"GET FILE='data.csv'.\nREGRESSION /DEPENDENT y /METHOD=ENTER {terms} {origin}.\n"
    elif d["kind"] == "NLS":
        p2 = " ".join(f"{p}={v!r}" for p, v in zip(d["params"], d["start2"]))
        syn = f"GET FILE='data.csv'.\nNLR {cols[0]} /PRED = {d['model']} /PARAMETERS {p2}.\n"
    else:
        syn = f"GET FILE='data.csv'.\nONEWAY {cols[1]} BY {cols[0]}.\n"
    return csv, syn
