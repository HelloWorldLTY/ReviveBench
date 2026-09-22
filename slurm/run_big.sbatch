#!/bin/bash
#SBATCH --job-name=revive_big
#SBATCH --partition=day
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=10:00:00
#SBATCH --output=logs/%x_%j.out
cd "${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export OMP_NUM_THREADS=8
python3 harness/run_task.py --task "$1" --condition "$2" --model "$3" --run-id "$4" --max-turns "${5:-120}" --agent-timeout 14400
