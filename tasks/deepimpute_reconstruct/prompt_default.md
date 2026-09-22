You are restoring a scientific software package whose core module was lost.

This repository is `deepimpute` (Arisdakessian et al., Genome Biology 2019), a deep-learning single-cell RNA-seq imputation tool. Read SITUATION.md and ENVIRONMENT.md first. The file `deepimpute/multinet.py` is missing; reconstruct it so that the package works exactly as the original did:
- `from deepimpute.multinet import MultiNet` must work with the constructor and method signatures used by `deepimpute/deepImpute.py`, `tests/` and README (`MultiNet(learning_rate, batch_size, max_epochs, patience, ncores, loss, output_prefix, sub_outputdim, verbose, seed, architecture)`; `fit(raw, cell_subset, NN_lim, genes_to_impute, n_pred, ntop, minVMR, mode)`; `predict(raw, imputed_only, policy)`; attributes `targets`, `predictors`, `test_metrics`).
- Method must follow the paper: log1p-normalised counts; target genes selected by variance-over-mean ratio and split into sub-networks of `sub_outputdim` genes; for each target subset the predictors are the top-`ntop` most correlated genes; one hidden dense (ReLU) + dropout layer per sub-network with the architecture given; weighted MSE loss (`wMSE`) that weights each entry by its true value; Adam optimiser; early stopping with `patience`; output combined back into a DataFrame with the input's index/columns; policy "restore" keeps every observed non-zero count, policy "max" keeps the max of observed and imputed.
- The `deepImpute` CLI (`python -m deepimpute.deepImpute examples/test.csv -o out.csv`) works end to end.
- `python -m pytest tests` passes (do not delete tests or weaken assertions).

Finish by writing `RESTORE_NOTES.md` describing what you reconstructed and any uncertainty. Work autonomously; do not ask questions.
