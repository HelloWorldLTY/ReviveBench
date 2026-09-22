#!/bin/bash
#SBATCH --job-name=tc_verify
#SBATCH --partition=day
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x_%j.out
cd "${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export PATH=$PWD/envs/py312_numpy/bin:$PATH
RUN=$1; N=${2:-120}
python3 toolchain/verify_toolchain.py --workspace toolchain/runs/$RUN/workspace \
    --out toolchain/runs/$RUN/acceptance.json --fuzz-n $N
python3 - <<PY
import json,pathlib
p=pathlib.Path("toolchain/runs/$RUN/acceptance.json")
if p.exists():
    r=json.loads(p.read_text()); print("SCORE", r["score"])
    for k,c in r["checks"].items(): print(f'  {"OK  " if c["pass"] else "FAIL"} {k:24s} {c.get("detail","")[:150]}')
PY
