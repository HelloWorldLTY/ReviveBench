#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -rf "$WS"/.travis.yml "$WS"/.bumpversion.cfg
rm -f "$WS/gapfill/subnet.py"            # <- the lost module
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.9 with TensorFlow 2.10 / Keras 2.10, NumPy 1.23, pandas 1.5, scipy, scikit-learn, pytest
(the versions this package was written for). Do not change these packages.
EON
cat > "$WS/SITUATION.md" <<'EON'
# Situation
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
