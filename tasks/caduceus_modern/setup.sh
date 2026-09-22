#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
rm -rf "$WS"/.ipynb_checkpoints
mkdir -p "$WS/hf_model"; cp "$HERE"/hidden/data/hf_model/*.py "$HERE"/hidden/data/hf_model/*.json "$HERE"/hidden/data/hf_model/model.safetensors "$WS/hf_model/"
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH: Python 3.11 with torch >= 2.5 (CUDA 12.x build), transformers >= 4.45, einops, huggingface_hub, pytest.
You may `pip install` more packages (e.g. mamba-ssm, causal-conv1d, triton) but may NOT downgrade torch or transformers below
those versions (verification checks this). A GPU is attached to this job (`nvidia-smi`). CUDA toolkit for building
extensions: CUDA_HOME is exported for this job and points at a CUDA 12.x toolkit (nvcc on PATH). No network-independent constraints:
pip/GitHub/HF are reachable. `hf_model/` is a local copy of the HF checkpoint
`kuleshov-group/caduceus-ps_seqlen-131k_d_model-256_n_layer-16` (config, weights, and its own remote-code modeling files).
EON
