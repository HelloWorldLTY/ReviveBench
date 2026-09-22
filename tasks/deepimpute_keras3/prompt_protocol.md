You are restoring an abandoned scientific software package so that it works again. Follow this restoration protocol strictly.

This repository is `deepimpute`, a deep-learning single-cell RNA-seq imputation tool (Arisdakessian et al., Genome Biology 2019). Its last commit is from 2022 and it no longer works in the current Python environment. Read ENVIRONMENT.md for the environment you must target (Python 3.11, TensorFlow >= 2.16 / Keras 3, NumPy >= 2, pandas >= 2). Do not downgrade those packages.

Protocol:
1. INVENTORY. Read setup.py, the package modules, tests/ and README. Write down the public API and the intended behaviour of each entry point (fit/predict semantics, CLI flags, output format) before changing anything.
2. REPRODUCE. Install (`pip install -e .`) and run `python -m pytest tests -x -q` and the CLI on `examples/test.csv`. Record every failure with its traceback.
3. ROOT-CAUSE TABLE. For each failure, classify it: (a) removed/renamed third-party API, (b) changed default behaviour of a dependency, (c) packaging/metadata, (d) genuine bug. Find the exact upstream change (e.g. Keras 3 removed `keras.backend` functions X, pandas 2 removed `DataFrame.groupby(axis=1)`, NumPy 2 changed `np.float_`).
4. MINIMAL, FAITHFUL PATCH. Fix each root cause with the smallest change that preserves the ORIGINAL numerical behaviour (same architecture, loss, optimizer, training schedule, gene selection). Do not re-design the method. Prefer forward-compatible code over version branches.
5. VERIFY. All tests in tests/ pass (you may adapt tests only where they call removed third-party APIs; never delete tests or weaken assertions). Run an end-to-end sanity check: mask 10% of non-zero entries of examples/test.csv, fit, predict with policy="restore", confirm observed counts are preserved exactly, output has the same shape/index/columns, no NaNs, and imputed values correlate with the masked-out truth.
6. REGRESSION GUARD. Add one small test that encodes the sanity check from step 5 so future rot is caught.
7. REPORT. Write `RESTORE_NOTES.md`: root-cause table, changes, verification evidence, and anything you could not restore.

Work autonomously; do not ask questions.
