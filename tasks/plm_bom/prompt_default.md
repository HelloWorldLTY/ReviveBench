Build `plmx`, a clean-room product lifecycle management core (Teamcenter / Windchill / ENOVIA class), in this workspace.

Read README.md, SPEC.md and ENVIRONMENT.md. Deliver `bash run_plm.sh <query.json> <out.json>`: it must apply the engineering change orders to the bill of material, then answer each query — BOM explosion with quantity roll-up under a date and option set, transitive where-used, the effective revision of a part, and engineering change impact — reporting results in query order.

It is invoked as `bash run_plm.sh ...` with an arbitrary working directory, so it must be a shell script that resolves its own files from the script's own location.

Python + NumPy only — no graph, dataframe or date libraries, and the environment is checked. Every answer is a set or an integer fixed exactly by the rules, so nothing carries a tolerance. Validate against every example in examples/.

Work autonomously; do not ask questions.
