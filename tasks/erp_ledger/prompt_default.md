Build `erpcore`, a clean-room ERP transactional core (SAP S/4HANA class), in this workspace.

Read README.md, SPEC.md and ENVIRONMENT.md. Deliver `bash run_erp.sh <scenario.json> <out.json>`: it must apply every business document in order — journals, goods receipts and issues, sales, revaluations, multi-currency journals and period closes — maintaining a double-entry general ledger and moving-average inventory valuation, then run MRP over the BOM and write the trial balance, stock, rejection list, planned orders, BOM cycles and closing equity.

It is invoked as `bash run_erp.sh ...`, so it must be a shell script with a shebang, not a Python file named `.sh`.

Python + NumPy only — no ERP, accounting or dataframe libraries, and the environment is checked. Everything is exact integer arithmetic: money in minor units, quantities in whole pieces, and there are no tolerances anywhere in the grading. Validate against every example in examples/, which pairs a scenario with its expected answer.

Work autonomously; do not ask questions.
