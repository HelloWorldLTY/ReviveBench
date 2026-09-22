# statsx — specification of the statistical analysis engine (SAS/SPSS class)

You are building `statsx`, a clean-room statistical engine that executes an SPSS-style syntax subset and writes results as JSON.
Numerical accuracy is the point: results are graded against certified reference values with the NIST "log relative error"
LRE = -log10(|estimate - certified| / |certified|). Targets: LRE >= 7 on "lower", >= 6 on "average", >= 4 on "higher" difficulty
problems (ill-conditioned polynomial designs such as a 10th-degree polynomial in x ~ -4..-9, and nonlinear fits from hard starting values).

## Command line (must exist at the workspace root)
    bash run_engine.sh <script.sps> <out.json>
Run from an arbitrary working directory; relative file names in the script are relative to that working directory.

## Syntax (one command per line, terminated by a period; keywords are case-insensitive)
    GET FILE='data.csv'.
        Load a CSV with a header row. All columns are numeric.
    REGRESSION /DEPENDENT y /METHOD=ENTER <terms> [/NOORIGIN | /ORIGIN].
        Ordinary least squares. Terms are column names, or powers `x^k` of a column. /NOORIGIN (default) fits an intercept, /ORIGIN fits
        no intercept. Output block: {"command":"REGRESSION","dependent":"y","terms":[...],"intercept":bool,
          "coefficients":[b0?, b1, ...] (intercept first when present, then terms in order), "std_errors":[...],
          "residual_sd": s, "r_squared": r2, "df_regression": p, "df_residual": n-p(-1),
          "ss_regression": .., "ss_residual": .., "ms_regression": .., "ms_residual": .., "f": ..}
        r_squared with /ORIGIN follows the NIST/SAS convention (uncorrected total sum of squares).
    NLR y /PRED = <expression> /PARAMETERS b1=<start> b2=<start> ....
        Nonlinear least squares minimising sum (y - PRED)^2 over the parameters. The expression uses + - * / ^, parentheses,
        column names, parameter names, numeric literals, and functions exp, log, sqrt, sin, cos, arctan, and the constant pi.
        Output block: {"command":"NLR","dependent":"y","parameters":["b1",...],"estimates":[...],"std_errors":[...],
          "residual_ss": .., "residual_sd": .., "df_residual": n-p, "converged": bool, "iterations": k}
        Standard errors are the usual asymptotic ones: sqrt(diag(s^2 (J'J)^-1)) with s^2 = RSS/(n-p) and J the Jacobian at the solution.
    ONEWAY y BY g.
        One-way analysis of variance of y across the levels of g. Output block: {"command":"ONEWAY","dependent":"y","factor":"g",
          "between_df":..,"between_ss":..,"between_ms":..,"within_df":..,"within_ss":..,"within_ms":..,"f":..,"r_squared":..,"residual_sd":..}
    DESCRIPTIVES VARIABLES=<cols>.
        Output block: {"command":"DESCRIPTIVES","stats":{"col":{"n":..,"mean":..,"sd":..,"min":..,"max":..}}}

## Output file
A JSON object {"results":[<block>, <block>, ...]} in command order. Numbers are plain JSON floats (full double precision).

## Rules
- Implement the numerics yourself on top of Python + NumPy (no SciPy/statsmodels/scikit-learn/lmfit/patsy or other statistics or
  optimisation libraries; verification checks the environment). Think about conditioning: centring/scaling, QR/SVD, and iterative
  refinement matter for the hard cases.
- Write tests. Example scripts with certified answers are in examples/.
