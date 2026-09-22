# ReviveBench

Can a coding agent turn **dead code** — scientific software that no longer runs — and **static pages** —
a published specification with no open implementation — into working software? ReviveBench answers both
with verifiers the agent never sees.

The suite has two task families:

* **Revival (10 tasks).** Restore scientific software broken by dependency rot (Keras 3, NumPy 2), a
  deleted core module, a 2019 C++ build under Python 3.12 (PyMOL), a Java 14 platform under JDK 21
  (QuPath), and GPU kernels for a DNA foundation model (Caduceus). Three further tasks come from
  repositories created after the models' knowledge cutoff. Every starting workspace fails its verifier.
* **Clean-room reconstruction (13 engines).** Build the core engine of commercial industrial software
  from an open standard alone: statistics, SPICE, PLC runtime, finite elements, 2D and 3D CAD, logic
  synthesis, place-and-route, CFD, ERP, SCADA/DCS, MES and PLM. The agent gets a specification and three
  worked examples; existing implementations are absent from the environment and checked for.

Grading spans three incompatible notions of correctness: numerical tolerance, exact or formal checks
(Yosys SAT equivalence, exact mesh topology), and transactional invariants with no tolerance at all.

## What is in this directory

| Path | Contents |
|---|---|
| `harness/` | Run one task (`run_task.py`), aggregate results, build the matrix and the paper tables, and the Anthropic↔OpenAI protocol adapter |
| `tasks/` | Task definitions: `task.json`, `setup.sh`, prompts, and `hidden/` verifiers, references and generators |
| `slurm/` | Batch scripts for a Slurm cluster, including the adapter/guard scripts for non-Anthropic models |
| `contamination/` | Obfuscated and post-cutoff task generators, similarity and cohort analysis |
| `toolchain/` | The multi-module scale-up (`plcforge`) and its differential fuzzer |
| `design/` | Requirement-driven part design driven through the agent-built CAD engine |
| `paper/figures/` | Scripts that draw the three paper figures from the run records |
| `tools/check_port.py` | Verifies this English port differs from the original only in wording and the declared changes |

Not included, because they are large or regenerable: per-run workspaces and trajectories (`runs/`,
about 32 GB), task conda environments (`envs/`, about 22 GB), downloaded datasets, and API keys.

## Configuration

Everything resolves paths and endpoints from the environment; nothing is hardcoded to one machine.

| Variable | Meaning |
|---|---|
| `REVIVE_ROOT` | Data root that holds `runs/`, `envs/`, `results/`, `tasks/`. Defaults to this repository |
| `REVIVE_BEDROCK_URL`, `REVIVE_BEDROCK_HOST` | Bedrock proxy endpoint, if you route Anthropic models through one |
| `REVIVE_GW_HOST`, `REVIVE_GW_OPENAI` | Gateway that exposes non-Anthropic models in OpenAI form |
| `REVIVE_KIMI_HOST`, `REVIVE_GLM_BASE` | Provider endpoints used by the corresponding batch scripts |
| `REVIVE_*_KEYFILE` | Path to a file holding one API key, mode 0600. No key is stored in this repository |
| `REVIVE_JAVA21_HOME`, `REVIVE_CUDA_HOME` | JDK 21 and CUDA 12.x installs, for the QuPath and Caduceus tasks |
| `REVIVE_CONDA_BIN`, `REVIVE_CONDA_PKGS`, `REVIVE_PIP_CACHE` | conda `bin/`, package cache and pip cache. All default inside `$REVIVE_ROOT` |
| `REVIVE_TAILSCALE_DIR` | tailscale install, only for the batch scripts that reach a host over a tailnet |
| `REVIVE_TOKEN_FIELD` | `max_tokens` or `max_completion_tokens`. Providers differ, and one silently ignores the wrong field — the batch scripts verify the cap is honoured before running |

## Running

```bash
export REVIVE_ROOT=/path/to/data-root          # holds runs/, envs/, results/

# one task, one model
python3 harness/run_task.py --task stats_nist --condition protocol \
        --model us.anthropic.claude-sonnet-5 --run-id m1 --max-turns 100

# a batch on Slurm: each line of the spec is "task condition model run_id max_turns"
sbatch slurm/batch_via_tailnet.sbatch slurm/spec_model_compare.txt 3

# results
python3 harness/aggregate.py                   # summary.json + summary.md
python3 harness/build_matrix.py --out matrix.csv
python3 harness/build_revival_table.py         # paper table, from run records
python3 paper/figures/fig2_results.py --with-glm
```

Tasks name site-specific paths as `${VAR}` in `task.json`; the harness expands them and refuses to
start when one is unset, rather than running with a half-expanded path.

A verifier never enters the workspace: `tasks/<task>/hidden/` is read only by the harness, after the
agent has finished.

## Reproducing the paper

`harness/build_matrix.py`, `build_tables.py`, `build_revival_table.py` and `build_appendix_tables.py`
regenerate every table from the run records, and `paper/figures/*.py` regenerate the three figures.
Each generator carries a self-check: re-running it over unchanged data must reproduce the shipped file
byte for byte.

## A note on what this suite measured

Building and auditing it produced **28 verifier defects — 24 false negatives and 2 false positives** —
more failures than the agents exhibited on their own. Two are worth repeating as warnings:

* A percentage tolerance (`passes >= 0.9 x cases`) admitted a netlist with a **proven** counterexample.
  Percentage tolerances suit numerical agreement; they are wrong where a failure is a proof of error.
* The CFD task awarded full marks to a 134-line program with no grid, which evaluates the closed-form
  solutions the specification prints and hard-codes the divergence diagnostic to zero. The verifier
  graded a **self-reported** number instead of recomputing it from the candidate's own output.

Three habits came out of that and are worth carrying into any benchmark of this kind: an
**achievability probe** (solve each case the way the specification prescribes, and check the threshold
is reachable), **consensus among candidates** (when N independent implementations agree with each other
and disagree with the oracle, suspect the asset), and **never grade a self-reported quantity**.

The same rule applies to the harness: verify that a setting is *honoured*, not merely *accepted*. One
provider returned HTTP 200 for an output-cap field it silently ignored, and every run of that model
went uncapped until we measured it.

## Licence

Not yet chosen — the code is released with the paper and the licence will be added before
publication. The task assets under `tasks/*/hidden/` derive from the upstream projects and open
standards each task names, and keep their own terms.
