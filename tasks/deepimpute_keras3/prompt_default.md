You are restoring an abandoned scientific software package so that it works again.

This repository is `deepimpute`, a deep-learning single-cell RNA-seq imputation tool (Arisdakessian et al., Genome Biology 2019). Its last commit is from 2022 and it no longer works in the current Python environment. Read ENVIRONMENT.md for the environment you must target (Python 3.11, TensorFlow >= 2.16 / Keras 3, NumPy >= 2, pandas >= 2). Do not downgrade those packages.

Goal: make the package fully functional again in THIS environment, preserving its original behaviour and public API:
- `pip install -e .` works; `from deepimpute.multinet import MultiNet` works; `MultiNet().fit(df)` / `.predict(df, policy="restore")` behave as documented (imputes zeros, keeps observed counts with the default "restore" policy, returns a DataFrame with the same index/columns).
- The `deepImpute` command-line entry point (`deepimpute/deepImpute.py`, `deepimpute/parser.py`) works end to end on `examples/test.csv`.
- The test suite in `tests/` passes with `python -m pytest tests`. You may adapt tests only where they themselves call removed third-party APIs; do not delete tests or weaken assertions.
- Numerical behaviour should match the original method (same architecture, loss, training procedure, gene selection), not a re-design.

Finish by writing `RESTORE_NOTES.md` listing each root cause you found and what you changed. Work autonomously; do not ask questions.
