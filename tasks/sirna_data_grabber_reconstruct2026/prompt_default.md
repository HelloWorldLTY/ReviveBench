You are restoring a Python scientific software package whose core module was lost.

Read SITUATION.md and ENVIRONMENT.md first. The file `src/sirna_data/rank_confidence.py` of package `sirna_data` is missing, and so is the package's test suite. Reconstruct the module so that the package works exactly as it did before:
- Every name that other modules import from it must exist with the semantics implied by its call sites, README, docs and examples; keep the same public API (function/class names, signatures, return types, error behaviour) so that the original hidden test suite passes.
- Implement the actual functionality described by the documentation, not stubs. Match documented defaults, edge cases and numerical conventions exactly.
- `pip install -e .` must work and `import sirna_data` must succeed; write your own tests for the reconstructed module and run them.

Finish by writing `RESTORE_NOTES.md` describing what you reconstructed and any uncertainty. Work autonomously; do not ask questions.
