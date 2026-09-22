#!/usr/bin/env python3
"""Reference statsx implementation (numpy + scipy) used only to calibrate the verifier thresholds.
Usage: reference_engine.py <script.sps> <out.json>"""
import sys, re, json, math, numpy as np
from scipy.optimize import least_squares
def run(script):
    data, results = None, []
    for cmd in re.split(r"\.\s*\n", open(script).read()):
        cmd = cmd.strip()
        if not cmd: continue
        kw = cmd.split()[0].upper()
        if kw == "GET":
            f = re.search(r"FILE\s*=\s*'([^']+)'", cmd, re.I).group(1)
            rows = [l.strip().split(",") for l in open(f) if l.strip()]
            data = {c: np.array([float(r[i]) for r in rows[1:]]) for i, c in enumerate(rows[0])}
        elif kw == "REGRESSION":
            dep = re.search(r"/DEPENDENT\s+(\w+)", cmd, re.I).group(1)
            terms = re.search(r"/METHOD\s*=\s*ENTER\s+([^/]+)", cmd, re.I).group(1).split()
            intercept = not re.search(r"/ORIGIN", cmd, re.I)
            cols = []
            for tm in terms:
                m = re.match(r"(\w+)\^(\d+)$", tm); cols.append(data[m.group(1)] ** int(m.group(2)) if m else data[tm])
            X = np.column_stack(([np.ones(len(data[dep]))] if intercept else []) + cols); y = data[dep]
            Q, R = np.linalg.qr(X); b = np.linalg.solve(R, Q.T @ y)
            for _ in range(3):  # iterative refinement
                r = y - X @ b; b = b + np.linalg.solve(R, Q.T @ r)
            res = y - X @ b; n, p = X.shape; dfr = n - p
            rss = float(res @ res); s2 = rss / dfr
            cov = s2 * np.linalg.inv(R.T @ R)
            sst = float(((y - y.mean()) ** 2).sum()) if intercept else float((y ** 2).sum())
            ssr = sst - rss; dfreg = p - 1 if intercept else p
            results.append({"command": "REGRESSION", "dependent": dep, "terms": terms, "intercept": intercept, "coefficients": b.tolist(),
                            "std_errors": np.sqrt(np.diag(cov)).tolist(), "residual_sd": math.sqrt(s2), "r_squared": 1 - rss / sst,
                            "df_regression": dfreg, "df_residual": dfr, "ss_regression": ssr, "ss_residual": rss,
                            "ms_regression": ssr / dfreg, "ms_residual": s2, "f": (ssr / dfreg) / s2})
        elif kw == "NLR":
            dep = cmd.split()[1]
            expr = re.search(r"/PRED\s*=\s*(.+?)\s*/PARAMETERS", cmd, re.I | re.S).group(1).strip().replace("^", "**")
            params = re.findall(r"(b\d+)\s*=\s*(\S+)", cmd.split("/PARAMETERS", 1)[1])
            names = [p for p, _ in params]; x0 = np.array([float(v) for _, v in params])
            env = {k: v for k, v in data.items()}; env.update({"exp": np.exp, "log": np.log, "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "arctan": np.arctan, "pi": math.pi})
            def pred(b):
                e = dict(env); e.update(dict(zip(names, b))); return eval(expr, {"__builtins__": {}}, e)
            y = data[dep]
            sol = least_squares(lambda b: pred(b) - y, x0, method="lm", xtol=1e-15, ftol=1e-15, gtol=1e-15, max_nfev=20000)
            J = sol.jac; rss = float(sol.fun @ sol.fun); n, p = len(y), len(names); s2 = rss / (n - p)
            cov = s2 * np.linalg.inv(J.T @ J)
            results.append({"command": "NLR", "dependent": dep, "parameters": names, "estimates": sol.x.tolist(), "std_errors": np.sqrt(np.diag(cov)).tolist(),
                            "residual_ss": rss, "residual_sd": math.sqrt(s2), "df_residual": n - p, "converged": bool(sol.success), "iterations": int(sol.nfev)})
        elif kw == "ONEWAY":
            m = re.match(r"ONEWAY\s+(\w+)\s+BY\s+(\w+)", cmd, re.I); y, g = data[m.group(1)], data[m.group(2)]
            levels = np.unique(g); gm = y.mean(); ssb = sum(((y[g == l].mean() - gm) ** 2) * (g == l).sum() for l in levels)
            ssw = sum(((y[g == l] - y[g == l].mean()) ** 2).sum() for l in levels); dfb, dfw = len(levels) - 1, len(y) - len(levels)
            results.append({"command": "ONEWAY", "dependent": m.group(1), "factor": m.group(2), "between_df": dfb, "between_ss": float(ssb), "between_ms": float(ssb / dfb),
                            "within_df": dfw, "within_ss": float(ssw), "within_ms": float(ssw / dfw), "f": float((ssb / dfb) / (ssw / dfw)), "r_squared": float(ssb / (ssb + ssw)), "residual_sd": math.sqrt(ssw / dfw)})
        elif kw == "DESCRIPTIVES":
            cols = re.search(r"VARIABLES\s*=\s*(.+)", cmd, re.I).group(1).split()
            results.append({"command": "DESCRIPTIVES", "stats": {c: {"n": int(len(data[c])), "mean": float(data[c].mean()), "sd": float(data[c].std(ddof=1)), "min": float(data[c].min()), "max": float(data[c].max())} for c in cols}})
    return {"results": results}
json.dump(run(sys.argv[1]), open(sys.argv[2], "w"), indent=1)
