#!/bin/bash
#SBATCH --job-name=revive_gpu
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=logs/%x_%j.out
cd "${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export OMP_NUM_THREADS=8
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
python3 harness/run_task.py --task "$1" --condition "$2" --model "$3" --run-id "$4" --max-turns "${5:-100}" --agent-timeout 14400
