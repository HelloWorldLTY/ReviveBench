"""Hidden functional check for DCA: masked-recovery denoising + latent + info outputs.
Usage: python functional.py <csv> <out.json>"""
import sys, json, time, warnings
import numpy as np, pandas as pd, anndata as ad
warnings.filterwarnings("ignore")
from scipy.stats import pearsonr
from dca.api import dca

csv, out = sys.argv[1], sys.argv[2]
data = pd.read_csv(csv, index_col=0)
vals = data.values.astype(float)
rng = np.random.RandomState(0)
nz = np.argwhere(vals > 0)
sel = nz[rng.choice(len(nz), size=int(0.10 * len(nz)), replace=False)]
masked = vals.copy(); masked[sel[:, 0], sel[:, 1]] = 0

def make_adata():
    a = ad.AnnData(X=masked.astype(np.float32).copy())
    a.obs_names = [str(x) for x in data.index]; a.var_names = [str(x) for x in data.columns]
    return a

res = {}
t0 = time.time()
ret = dca(make_adata(), mode="denoise", ae_type="nb-conddisp", copy=True, epochs=150,
          random_state=0, threads=4, verbose=False)
res["fit_seconds"] = round(time.time() - t0, 1)
X = ret.X.toarray() if hasattr(ret.X, "toarray") else np.asarray(ret.X)
den = pd.DataFrame(X, index=ret.obs_names, columns=ret.var_names)
res["shape_ok"] = bool(den.shape[0] == data.shape[0] and set(den.columns) <= set(map(str, data.columns))
                       and den.shape[1] >= 0.9 * data.shape[1])
res["nan_free"] = bool(np.isfinite(X).all()); res["nonneg"] = bool((X >= -1e-6).all())
col_pos = {c: i for i, c in enumerate(den.columns)}
keep = np.array([str(data.columns[j]) in col_pos for j in sel[:, 1]])
s = sel[keep]
true = vals[s[:, 0], s[:, 1]]
pred = den.values[s[:, 0], [col_pos[str(data.columns[j])] for j in s[:, 1]]]
res["n_masked_scored"] = int(len(s))
res["r_masked"] = float(pearsonr(np.log1p(true), np.log1p(pred))[0])
gene_mean = masked.mean(axis=0)[s[:, 1]]
res["r_genemean_baseline"] = float(pearsonr(np.log1p(true), np.log1p(gene_mean))[0])
res["r_resid"] = float(pearsonr(np.log1p(true) - np.log1p(gene_mean), np.log1p(pred) - np.log1p(gene_mean))[0])
# latent mode
ret2 = dca(make_adata(), mode="latent", copy=True, epochs=20, random_state=0, threads=4, verbose=False)
res["latent_ok"] = bool("X_dca" in ret2.obsm and ret2.obsm["X_dca"].shape == (data.shape[0], 32)
                        and np.isfinite(ret2.obsm["X_dca"]).all())
# zinb with info
ret3 = dca(make_adata(), mode="denoise", ae_type="zinb-conddisp", copy=True, epochs=20, random_state=0,
           threads=4, verbose=False, return_info=True)
res["info_ok"] = bool("X_dca_dropout" in ret3.obsm_keys() and "dca_loss_history" in ret3.uns_keys()
                      and "X_dca_dispersion" in ret3.obsm_keys())
json.dump(res, open(out, "w"), indent=1); print(json.dumps(res))
