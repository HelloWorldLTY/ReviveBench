"""Hidden functional check for deepimpute: masked-recovery of non-zero counts.
Usage: python functional.py <csv> <out.json>   (must run with the package importable)"""
import sys, json, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
from scipy.stats import pearsonr
from deepimpute.multinet import MultiNet

csv, out = sys.argv[1], sys.argv[2]
data = pd.read_csv(csv, index_col=0)
vals = data.values.astype(float)
rng = np.random.RandomState(0)
nz = np.argwhere(vals > 0)
sel = nz[rng.choice(len(nz), size=int(0.10 * len(nz)), replace=False)]
masked = vals.copy(); masked[sel[:, 0], sel[:, 1]] = 0
mdf = pd.DataFrame(masked, index=data.index, columns=data.columns)

t0 = time.time()
m = MultiNet(seed=123, ncores=4, verbose=0)
m.fit(mdf)
imp = m.predict(mdf, policy="restore")
fit_s = time.time() - t0

res = {"fit_seconds": round(fit_s, 1)}
res["shape_ok"] = bool(imp.shape == data.shape and list(imp.index) == list(data.index)
                       and list(imp.columns) == list(data.columns))
iv = imp.values.astype(float)
res["nan_free"] = bool(np.isfinite(iv).all())
res["nonneg"] = bool((iv >= -1e-6).all())
obs = masked > 0
res["restore_exact"] = bool(np.allclose(iv[obs], masked[obs], rtol=1e-5, atol=1e-5))
def _flat(x):
    out = []
    stack = [x]
    while stack:
        y = stack.pop()
        if isinstance(y, (list, tuple, set)) or (hasattr(y, 'tolist') and getattr(y, 'ndim', 0) > 0):
            stack.extend(list(y))
        else:
            out.append(y.item() if hasattr(y, 'item') else y)
    return out
targets = set(_flat(m.targets))
is_t = np.array([c in targets for c in data.columns])
s = sel[is_t[sel[:, 1]]]
res["n_target_genes"] = int(is_t.sum())
res["n_masked_in_targets"] = int(len(s))
true = vals[s[:, 0], s[:, 1]]; pred = iv[s[:, 0], s[:, 1]]
res["frac_masked_filled"] = float((pred > 0).mean())
res["r_masked"] = float(pearsonr(np.log1p(true), np.log1p(pred))[0]) if len(s) > 10 else float("nan")
gene_mean = np.asarray(mdf.mean(axis=0))[s[:, 1]]
res["r_genemean_baseline"] = float(pearsonr(np.log1p(true), np.log1p(gene_mean))[0]) if len(s) > 10 else float("nan")
res["r_resid"] = float(pearsonr(np.log1p(true) - np.log1p(gene_mean), np.log1p(pred) - np.log1p(gene_mean))[0]) if len(s) > 10 else float("nan")
res["pred_std_within_gene"] = float(np.mean([np.std(np.log1p(pred[s[:, 1] == g])) for g in np.unique(s[:, 1])[:200] if (s[:, 1] == g).sum() > 3]))
json.dump(res, open(out, "w"), indent=1)
print(json.dumps(res))
