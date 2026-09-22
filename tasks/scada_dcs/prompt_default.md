Build `scadax`, a clean-room SCADA/DCS runtime (Wonderware / Ignition / DeltaV class), in this workspace.

Read README.md, SPEC.md and ENVIRONMENT.md. Deliver `bash run_scada.sh <scenario.json> <out.json>`: it must run a deterministic scan cycle over the tag database — sampling inputs with a zero-order hold, evaluating an ISA-18.2 style alarm state machine with deadband and on/off delays, running PID loops with anti-windup, recording history, and building a Modbus holding-register image — then report the alarm journal, per-scan loop outputs, historian query results and the register image.

It is invoked as `bash run_scada.sh ...` with an arbitrary working directory, so it must be a shell script that resolves its own files from the script's own location.

Python + NumPy only — no Modbus, OPC or dataframe libraries, and the environment is checked. The engine is deterministic, so the alarm journal, the integer aggregates and the register image are graded exactly, with no tolerance; only float outputs carry a 1e-9 band. Validate against every example in examples/.

Work autonomously; do not ask questions.
