#!/usr/bin/env python3
"""Build tasks/deepimpute_reconstruct_obf: deepimpute with every identifier, file and package name renamed
consistently (repo + hidden verifier), and the paper/GitHub references removed. If a model reconstructs
the missing core module here, recall of the original file cannot be the explanation."""
import os
import pathlib
import io, json, pathlib, re, shutil, tarfile
ROOT = pathlib.Path(os.environ.get("REVIVE_ROOT") or pathlib.Path(__file__).resolve().parents[1])
SRC = ROOT / "tasks" / "deepimpute_reconstruct"
DST = ROOT / "tasks" / "deepimpute_reconstruct_obf"
MAP = [  # longest first; whole-word, case-sensitive
    ("get_distance_matrix", "predictor_correlation"), ("loadDefaultArchitecture", "default_layers"),
    ("maskedArrays_test", "masking_test"), ("deepImpute_test", "gapfill_cli_test"), ("multinet_test", "subnet_test"),
    ("setPredictors", "assign_predictors"), ("sub_outputdim", "block_size"), ("test_metrics", "holdout_metrics"),
    ("output_prefix", "model_dir"), ("inspect_data", "validate_counts"), ("maskedArrays", "masking"),
    ("MaskedArray", "Masker"), ("filter_genes", "select_genes"), ("setTargets", "assign_targets"),
    ("deepimpute", "gapfill"), ("deepImpute", "gapfill_cli"), ("DeepImpute", "GapFill"), ("multinet", "subnet"),
    ("MultiNet", "SubnetImputer"), ("NN_lim", "gene_limit"), ("minVMR", "min_vmr"), ("n_pred", "n_predictors"),
    ("wMSE", "weighted_mse"), ("ntop", "top_k"), ("util", "helpers"), ("parser", "cli_args"),
]
DROP_LINE = re.compile(r"Arisdakessian|Genome Biology|github\.com|doi\.org|bioRxiv|Garmire|citation|cite", re.I)

def rename(text):
    for a, b in MAP:
        text = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(a) + r"(?![A-Za-z0-9_])", b, text)
    return text

def rename_path(p):
    parts = [rename(x) if not x.endswith((".csv", ".ipynb")) else x for x in p.split("/")]
    return "/".join(parts)

def convert_tar(src_tar, dst_tar):
    out = tarfile.open(dst_tar, "w:gz")
    with tarfile.open(src_tar) as t:
        for m in t.getmembers():
            if not m.isfile(): continue
            data = t.extractfile(m).read()
            name = rename_path(m.name)
            if m.name.endswith((".py", ".md", ".txt", ".cfg", ".ini", "makefile", "Dockerfile", ".yml", ".toml")):
                txt = data.decode("utf-8", "replace")
                if m.name.endswith((".md", ".txt", ".py")):
                    txt = "\n".join(l for l in txt.splitlines() if not DROP_LINE.search(l)) + "\n"
                data = rename(txt).encode()
            if m.name.endswith(".ipynb"):  # drop the notebook: it contains prose naming the tool
                continue
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = m.mode
            out.addfile(info, io.BytesIO(data))
    out.close()

if DST.exists(): shutil.rmtree(DST)
(DST / "hidden" / "pristine").mkdir(parents=True); (DST / "hidden" / "data").mkdir()
convert_tar(SRC / "hidden/pristine/repo.tar.gz", DST / "hidden/pristine/repo.tar.gz")
shutil.copy(SRC / "hidden/data/test.csv", DST / "hidden/data/test.csv")
for f in ("functional.py", "verify.py"):
    (DST / "hidden" / f).write_text(rename((SRC / "hidden" / f).read_text()))
shutil.copy(SRC / "hidden/oracle_reference.json", DST / "hidden/oracle_reference.json")
task = json.loads((SRC / "task.json").read_text())
task.update({"id": "deepimpute_reconstruct_obf", "tier": "T3-reconstruct-obfuscated",
             "description": "deepimpute_reconstruct with all identifiers/file names renamed (package `gapfill`, class `SubnetImputer`, ...) and paper/GitHub references removed. Same hidden verifier (renamed). Controls for verbatim recall of the original module.",
             "obfuscation_map": MAP})
(DST / "task.json").write_text(json.dumps(task, indent=2))
setup = (SRC / "setup.sh").read_text()
setup = rename(setup).replace('rm -f "$WS/gapfill/subnet.py"', 'rm -f "$WS/gapfill/subnet.py"')
setup = re.sub(r"# Situation\n.*?EON\n", '''# Situation
The file `gapfill/subnet.py` (the core of the package: class `SubnetImputer` plus module-level helpers
`predictor_correlation`, `weighted_mse`, `validate_counts`) was lost. Everything else is intact: `gapfill_cli.py`
(CLI wrapper that shows how SubnetImputer is called), `cli_args.py` (CLI flags and their documented defaults),
`helpers.py`, `masking.py`, `tests/` (exercise the API) and README.md.
Method summary (from the package documentation): single-cell RNA-seq imputation with an ensemble of small
feed-forward networks. Genes are ranked by variance-over-mean ratio; genes above `min_vmr` (or the first
`gene_limit` genes) are targets, split randomly into blocks of `block_size` genes. Each block gets its own
sub-network whose inputs are the `top_k` genes most correlated with the block's targets (predictors are drawn
from the genes not in the block); architecture = one hidden dense layer (ReLU) + dropout as given by
`architecture`, output layer = dense softplus of size `block_size`. Training: log1p counts, Adam optimiser with
`learning_rate`, loss = mean squared error weighted by the true value (`weighted_mse`), 5% of cells held out for
early stopping with `patience`. Prediction: expm1 of the outputs, non-target genes copied through, overflow/NaN set
to 0; policy "restore" puts every observed non-zero count back, policy "max" keeps max(observed, imputed).
EON
''', setup, flags=re.S)
(DST / "setup.sh").write_text(setup); (DST / "setup.sh").chmod(0o755)
for cond in ("default", "protocol"):
    p = rename((SRC / f"prompt_{cond}.md").read_text())
    p = "\n".join(l for l in p.splitlines() if not DROP_LINE.search(l))
    p = p.replace("This repository is `gapfill` (, a deep-learning", "This repository is `gapfill`, a deep-learning")
    p = re.sub(r"`gapfill` \([^)]*\)", "`gapfill`", p)
    (DST / f"prompt_{cond}.md").write_text(p)
print("built", DST); print((DST / "prompt_default.md").read_text()[:700])
