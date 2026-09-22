#!/bin/bash
#SBATCH --job-name=revive
#SBATCH --partition=day
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=logs/%x_%j.out
# usage: sbatch [--partition=gpu --gres=gpu:1] slurm/run.sbatch <task> <condition> <model> <run_id> [max_turns]
cd "${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export OMP_NUM_THREADS=8
python3 harness/run_task.py --task "$1" --condition "$2" --model "$3" --run-id "$4" --max-turns "${5:-80}"
