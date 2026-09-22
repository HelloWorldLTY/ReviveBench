Build `mesx`, a clean-room manufacturing execution core (Siemens Opcenter / Rockwell FactoryTalk class), in this workspace.

Read README.md, SPEC.md and ENVIRONMENT.md. Deliver `bash run_mes.sh <scenario.json> <out.json>`: it must schedule every work order's operations through finite-capacity work centres using the dispatch rule the spec defines, consume material lots FIFO while recording full genealogy, apply the scrap rule, and report the schedule, genealogy, stalled orders, material balance and OEE.

It is invoked as `bash run_mes.sh ...` with an arbitrary working directory, so it must be a shell script that resolves its own files from the script's own location.

Python + NumPy only — no scheduling or dataframe libraries, and the environment is checked. The engine is deterministic, so the schedule, genealogy and material balance are graded exactly, with no tolerance; only the OEE ratios carry a 1e-9 band. Validate against every example in examples/.

Work autonomously; do not ask questions.
