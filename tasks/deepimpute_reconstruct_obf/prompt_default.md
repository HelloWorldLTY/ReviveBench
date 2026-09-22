You are restoring a scientific software package whose core module was lost.

This repository is `gapfill`, a deep-learning single-cell RNA-seq imputation tool. Read SITUATION.md and ENVIRONMENT.md first. The file `gapfill/subnet.py` is missing; reconstruct it so that the package works exactly as the original did:
- `from gapfill.subnet import SubnetImputer` must work with the constructor and method signatures used by `gapfill/gapfill_cli.py`, `tests/` and README (`SubnetImputer(learning_rate, batch_size, max_epochs, patience, ncores, loss, model_dir, block_size, verbose, seed, architecture)`; `fit(raw, cell_subset, gene_limit, genes_to_impute, n_predictors, top_k, min_vmr, mode)`; `predict(raw, imputed_only, policy)`; attributes `targets`, `predictors`, `holdout_metrics`).
- Method must follow the description in SITUATION.md and README: log1p-normalised counts; target genes selected by variance-over-mean ratio and split into sub-networks of `block_size` genes; for each target subset the predictors are the top-`top_k` most correlated genes; one hidden dense (ReLU) + dropout layer per sub-network with the architecture given; weighted MSE loss (`weighted_mse`) that weights each entry by its true value; Adam optimiser; early stopping with `patience`; output combined back into a DataFrame with the input's index/columns; policy "restore" keeps every observed non-zero count, policy "max" keeps the max of observed and imputed.
- The `gapfill_cli` CLI (`python -m gapfill.gapfill_cli examples/test.csv -o out.csv`) works end to end.
- `python -m pytest tests` passes (do not delete tests or weaken assertions).

Finish by writing `RESTORE_NOTES.md` describing what you reconstructed and any uncertainty. Work autonomously; do not ask questions.
