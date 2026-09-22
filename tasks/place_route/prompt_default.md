Build `prx`, a clean-room standard-cell place-and-route engine (Cadence Innovus / Synopsys ICC2 class), in this workspace.

Read README.md, SPEC.md and ENVIRONMENT.md. Deliver `bash run_pnr.sh <design.json> <out.json>`: it must place every instance legally into rows — inside the die, row- and site-aligned, no overlaps, clear of blockages — then route every net on two metal layers (layer 1 horizontal, layer 2 vertical, joined by vias) so that every net's pins are connected and no two nets share a grid point, and report the half-perimeter wirelength of your own placement.

It is invoked as `bash run_pnr.sh ...` with an arbitrary working directory, so it must be a shell script that resolves its own files from the script's own location.

Python + NumPy only — no EDA or geometry libraries, and the environment is checked. Everything is on an integer grid and the legality, connectivity and wirelength-consistency checks carry no tolerance. Validate against every example in examples/.

Work autonomously; do not ask questions.
