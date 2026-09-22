You are restoring an old release of a scientific software package so that it builds and runs again on a modern toolchain.

This is the source tree of open-source PyMOL v2.3.0 (Schrödinger, February 2019), a molecular visualisation system: C++ core (layer0..layer5, ov, contrib) compiled as the `pymol._cmd` extension plus the Python package in `modules/`. It was written for Python 3.7-era `distutils`/`setup.py`, NumPy 1.x and 2019 system libraries. Read ENVIRONMENT.md: Python 3.12 (no distutils), NumPy >= 2, conda-forge toolchain; you may add libraries with pip or mamba but must not downgrade Python/NumPy and must not install a pre-built PyMOL.

Goal, in THIS environment:
- Build and install PyMOL from this tree into the environment (`pip install .` or `python setup.py install`, your choice) so that `import pymol`, `from pymol import cmd`, `import pymol2` work and the `pymol` launcher script runs headless (`pymol -cq script.pml`).
- Preserve the original behaviour: loading PDB files, selections and `count_atoms`, `get_distance`, `dss` secondary-structure assignment, `align` (RMSD), `get_fastastr`, and ray-traced rendering `cmd.png(..., ray=1)` without a display, all producing the same results as the original PyMOL 2.3 (fix build/API compatibility, do not change algorithms). NumPy interop (`cmd.get_coords`, `cmd.load_coords`) must work with NumPy 2.
- The relevant parts of the package's own test suite under `testing/` should pass headless (`python testing/testing.py --offscreen` or per-file pytest, as the tree supports); document what you ran.
- Write `RESTORE_NOTES.md`: root causes (build system, C++/compiler, NumPy C-API, Python 3.12 removals, dependency changes) and what you changed, plus the exact build command that works.

Work autonomously; do not ask questions.
