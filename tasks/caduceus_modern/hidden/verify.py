#!/usr/bin/env python3
"""Hidden verifier for caduceus_modern (needs a GPU). Never copied into the workspace."""
import argparse, json, pathlib, sys, tempfile
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "harness"))
from verify_common import PY, sh, make_env, check_env_constraints, pristine_tests_per_file, finish
TASK = json.loads((HERE.parent / "task.json").read_text())

PROPERTY = r'''
import sys, json, torch, numpy as np
from transformers import AutoModel, AutoModelForMaskedLM, AutoTokenizer, AutoConfig
ws, chunk_path = sys.argv[1], sys.argv[2]
res = {"cuda": torch.cuda.is_available()}
dev = "cuda"
tok = AutoTokenizer.from_pretrained(f"{ws}/hf_model", trust_remote_code=True)
model = AutoModel.from_pretrained(f"{ws}/hf_model", trust_remote_code=True).to(dev).eval()
res["n_params"] = sum(p.numel() for p in model.parameters())
rng = np.random.RandomState(0)
seqs = ["".join(rng.choice(list("ACGT"), size=2048)) for _ in range(4)]
rc = [s[::-1].translate(str.maketrans("ACGT", "TGCA")) for s in seqs]
ids = tok(seqs, add_special_tokens=False, return_tensors="pt")["input_ids"].to(dev)
ids_rc = tok(rc, add_special_tokens=False, return_tensors="pt")["input_ids"].to(dev)
with torch.no_grad():
    h = model(ids).last_hidden_state.float(); h_rc = model(ids_rc).last_hidden_state.float()
res["hidden_shape"] = list(h.shape)
res["finite"] = bool(torch.isfinite(h).all() and torch.isfinite(h_rc).all())
res["hidden_std"] = float(h.std())
rel = float((h_rc - h.flip(dims=(-2, -1))).norm() / (h.norm() + 1e-8))
res["rc_rel_err"] = rel
res["rc_equivariant"] = rel < 1e-3
# masked-LM sanity on real human DNA vs a randomly initialised twin
mlm = AutoModelForMaskedLM.from_pretrained(f"{ws}/hf_model", trust_remote_code=True).to(dev).eval()
cfg = AutoConfig.from_pretrained(f"{ws}/hf_model", trust_remote_code=True)
torch.manual_seed(0)
rand = AutoModelForMaskedLM.from_config(cfg, trust_remote_code=True).to(dev).eval()
dna = open(chunk_path).read().strip()
segs = [dna[i:i + 4096] for i in range(0, 4096 * 6, 4096)]
inp = tok(segs, add_special_tokens=False, return_tensors="pt")["input_ids"].to(dev)
mask_id = tok.mask_token_id
m = torch.rand(inp.shape, generator=torch.Generator().manual_seed(1)) < 0.15
m = m.to(dev)
x = inp.clone(); x[m] = mask_id
def acc(mdl):
    with torch.no_grad():
        logits = mdl(x).logits
    return float((logits.argmax(-1)[m] == inp[m]).float().mean())
res["mlm_acc_pretrained"] = acc(mlm); res["mlm_acc_random_init"] = acc(rand)
res["weights_loaded"] = res["mlm_acc_pretrained"] > 0.33 and res["mlm_acc_pretrained"] > res["mlm_acc_random_init"] + 0.05
print("PROP=" + json.dumps(res))
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skip-env-check", action="store_true")
    a = ap.parse_args()
    ws = pathlib.Path(a.workspace).resolve()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verify_")); env = make_env(ws)
    checks, metrics = {}, {}
    c, vers = check_env_constraints({} if a.skip_env_check else TASK["constraints"], tmp, env)
    checks["env_constraints"] = c; metrics["versions"] = vers

    rc, out = sh([PY, "-c", "import torch; assert torch.cuda.is_available(); print('GPU_OK', torch.cuda.get_device_name(0), torch.version.cuda)"], tmp, env, 300)
    checks["gpu_available"] = {"pass": rc == 0 and "GPU_OK" in out, "detail": out[-800:]}

    rc, out = sh([PY, "-c", "import mamba_ssm, causal_conv1d; from caduceus.modeling_caduceus import CaduceusConfig, CaduceusForMaskedLM; from caduceus.modeling_rcps import RCPSEmbedding; print('IMPORT_OK', mamba_ssm.__version__)"], tmp, env, 600)
    checks["import_kernels_and_package"] = {"pass": rc == 0 and "IMPORT_OK" in out, "detail": out[-1500:]}

    prop = tmp / "prop.py"; prop.write_text(PROPERTY)
    rc, out = sh([PY, str(prop), str(ws), str(HERE / "data" / "human_chunk.txt")], tmp, env, 1800)
    line = [l for l in out.splitlines() if l.startswith("PROP=")]
    if line:
        p = json.loads(line[-1][5:]); metrics["property"] = p
        ok = p.get("finite") and p.get("hidden_shape", [0])[-1] == 512 and p.get("hidden_std", 0) > 1e-3
        checks["pretrained_rc_equivariance"] = {"pass": bool(ok and p.get("rc_equivariant")), "detail": json.dumps(p)}
        checks["pretrained_weights_mlm"] = {"pass": bool(ok and p.get("weights_loaded")), "detail": json.dumps(p)}
    else:
        checks["pretrained_rc_equivariance"] = {"pass": False, "detail": out[-2500:]}
        checks["pretrained_weights_mlm"] = {"pass": False, "detail": out[-1000:]}

    checks["pristine_unit_tests"] = pristine_tests_per_file(HERE / "pristine" / "repo.tar.gz", tmp, env, "caduceus/tests/test_rcps.py", timeout=2400, workspace=ws, overlay=["caduceus/tests"],
        # upstream test bug: calls RCPSAddNormWrapper with prenorm=False (tensor) but iterates it as a tuple -> broken on the original code too
        pytest_args=("--deselect", "caduceus/tests/test_rcps.py::test_rcps_add_norm_wrapper"))
    finish(a.out, checks, metrics, tmp)


if __name__ == "__main__":
    main()
