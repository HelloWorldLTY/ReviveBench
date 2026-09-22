You are building a clean-room reimplementation of the core of a commercial statistics package (SAS PROC REG / NLIN / GLM, SPSS REGRESSION / NLR / ONEWAY). Follow this protocol strictly: (1) INVENTORY the spec: every command, option, output field and accuracy target; (2) design the numerics per problem class (conditioning analysis, scaling, QR/SVD, refinement, LM with trust region and analytic Jacobians); (3) IMPLEMENT incrementally with tests per command; (4) VERIFY on every example computing the NIST LRE, and stress-test with synthetic ill-conditioned problems and hard starting values; (5) REPORT. Read README.md, SPEC.md and ENVIRONMENT.md first.

Deliver `statsx` in this workspace:
- `bash run_engine.sh <script.sps> <out.json>` executes the SPSS-style syntax in SPEC.md and writes the JSON described there.
- Numerical accuracy is graded with NIST's log-relative-error against certified values (targets in SPEC.md), on problems that include severely ill-conditioned polynomial regressions (e.g. a 10th-degree polynomial with x in [-9, -3]) and nonlinear least squares from the harder of the two NIST starting values. Standard errors, residual standard deviation, R² and the ANOVA table must be as accurate as the estimates.
- Only Python + NumPy: implement your own QR/SVD-based least squares with appropriate scaling and iterative refinement, and your own Levenberg–Marquardt (or equivalent) with analytic or high-accuracy numerical derivatives and tight convergence.
- Verify against every example in examples/ (compute the LRE yourself) and write your own tests.

Finish with `NOTES.md` describing the algorithms and the accuracy you achieved on the examples. Work autonomously; do not ask questions.
