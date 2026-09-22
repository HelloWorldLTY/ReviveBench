You are restoring an abandoned scientific software package so that it works again.

This repository is `dca` (Deep Count Autoencoder; Eraslan, Simon et al., Nature Communications 2019), a denoising/latent-representation tool for single-cell RNA-seq count data. Its last commit is from 2022, its setup.py pins `keras>=2.4,<2.6` and `tensorflow<2.5`, and it no longer works in the current environment. Read ENVIRONMENT.md for the environment you must target (Python 3.11, TensorFlow >= 2.16 / Keras 3, NumPy >= 2, pandas >= 2, current scanpy/anndata). Do not downgrade those packages and do not switch to legacy `tf_keras`.

Goal: make the package fully functional again in THIS environment, preserving the original method and public API:
- `pip install -e .` works; `from dca.api import dca` works with its documented signature; `dca(adata, mode="denoise", copy=True)` returns an AnnData whose `.X` holds denoised expression; `mode="latent"` fills `.obsm["X_dca"]`; `return_info=True` fills `.obsm["X_dca_dropout"]` / dispersion / `.uns["dca_loss_history"]` as documented in the docstring; all autoencoder types in `dca.network.AE_types` (poisson, nb, nb-conddisp, nb-shared, nb-fork, zinb, zinb-conddisp, zinb-shared, zinb-fork, zinb-elempi) build and train.
- The `dca` command line (`python -m dca <counts.csv> <outdir>` and the `dca` console script) works end to end and writes `mean.tsv` (and `latent.tsv` etc. as before).
- The custom layers (`dca/layers.py`), losses (`dca/loss.py`: NB and ZINB negative log-likelihoods), network definitions and training loop must keep the ORIGINAL numerical behaviour (same architecture, loss, optimiser, size-factor handling, normalisation), not a re-design.
- `python -m pytest dca/test.py` passes (it downloads the paul15 dataset via scanpy). You may adapt tests only where they call removed third-party APIs; do not delete tests or weaken assertions.

Finish by writing `RESTORE_NOTES.md` listing each root cause you found and what you changed. Work autonomously; do not ask questions.
