# What this port changes

This directory is the English release of the ReviveBench code. Comments, docstrings and human-readable
messages are translated; program logic is unchanged. `tools/check_port.py` enforces that: it compares
each file's syntax tree against the original with string constants normalised, so any structural change
shows up, and it re-runs the table generators and requires byte-identical output.

## Deliberate differences from the original tree

1. **Data root from the environment.** The original resolved paths relative to the script, and several
   files hardcoded one absolute path. Here every script reads `$REVIVE_ROOT` and falls back to this
   repository. Affected: the files listed as `INTENTIONAL` in `tools/check_port.py`.
2. **No private infrastructure.** Gateway hostnames, a tailnet IP, a Bedrock proxy address and a peer
   name were replaced by required environment variables, so a missing value fails loudly instead of
   silently pointing at someone else's machine. No key material is present, in any form.
3. **Site paths in task definitions are placeholders.** `task.json` names JDK, CUDA and cache locations
   as `${VAR}`; `harness/run_task.py` expands them and asserts none is left unexpanded, so a missing
   variable stops the run instead of producing a wrong `JAVA_HOME`. The conda `bin/`, package cache and
   pip cache are configurable too, and default inside `$REVIVE_ROOT`. One task's own `ENVIRONMENT.md`
   named the cluster's CUDA install; it now states that `CUDA_HOME` is exported for the job, which is
   what `extra_env` already did.
4. **Relative Slurm log paths.** `#SBATCH --output` now writes `logs/%x_%j.out` under the submission
   directory.
5. **Artefacts dropped.** `contamination/recall/*.py` were model answers stored with a `.py` suffix,
   not source, and are not part of the code.

## Translation status

Every comment, docstring and message in the code is now English: harness, Slurm batch scripts and their
spec headers, the protocol adapter, the toolchain verifier, and all 13 hidden verifiers and their
generators. Each batch was followed by a full `tools/check_port.py` run, so no translation could quietly
change behaviour.

Two translations needed more than wording. In `tasks/place_route/hidden/`, the verifier classifies a
problem as placement or routing by matching substrings of the strings `ref_pnr.py` produces, so both
files were changed together and the classification re-checked against every problem string. In
`harness/report.py`, the generated HTML is the pilot report, which predates the GLM column and the
re-runs; the page now says so, because shipping its superseded figures in English without a marker
would misrepresent them.

Chinese that remains (65 lines) is **experimental input**, and translating it would change the
experiment rather than document it:

| File | Lines | Why it stays |
|---|---|---|
| `toolchain/PROJECT.md` | 62 | Copied into the workspace and read by the agent: it is the specification for the plcforge task |
| `tasks/erp_ledger/hidden/SPEC.md` | 1 | Copied into the workspace as `SPEC.md`; one parenthetical names the minor currency unit |
| `paper/figures/fig2_results.py` | 2 | A path to a data file in `$REVIVE_ROOT` whose name contains Chinese; renaming it would break reading the real artefact |
| `design/` requirement statements | - | The prompts the agents were given |
