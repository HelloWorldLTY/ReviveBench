#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS/examples"; cp "$HERE/hidden/SPEC.md" "$WS/SPEC.md"; cp "$HERE/hidden/drawings/d0.dxf" "$WS/examples/sample.dxf"
python3 - "$HERE" "$WS" <<'PY'
import json, sys, pathlib
here, ws = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); cmds = json.loads((here / "hidden/ref/commands.json").read_text())
ex = [c for c in cmds if c["name"].startswith("d0_")]
for c in ex:
    c = dict(c); c["cmd"] = dict(c["cmd"]); c["cmd"]["dxf"] = "sample.dxf"
    (ws / "examples" / f"{c['name']}.json").write_text(json.dumps({"command": c["cmd"], "expected": c["ref"]}, indent=1))
PY
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
`python` on PATH is Python 3.12 with NumPy and pytest only. No ezdxf / shapely / OpenCASCADE (verification checks the environment).
EON
cat > "$WS/README.md" <<'EON'
# cadx
Clean-room 2D CAD geometry engine with DXF I/O. Read SPEC.md. examples/ has a sample drawing plus, for each operation, the
command JSON and the expected answer (areas/perimeters/centroids/bboxes computed with a reference geometry library). The
hidden evaluation runs 31 operations on 6 drawings; DXF files you write are read back with a standard DXF library.
EON
