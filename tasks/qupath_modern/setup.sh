#!/bin/bash
set -e
WS=$1; HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WS"; tar xzf "$HERE/hidden/pristine/repo.tar.gz" -C "$WS"
mkdir -p "$WS/sample_data"; cp "$HERE/../_shared_data/CMU-1-Small-Region.svs" "$WS/sample_data/"
cat > "$WS/ENVIRONMENT.md" <<'EON'
# Target environment (fixed)
- JDK 21 (`java`, `javac` on PATH; JAVA_HOME set). No other JDK is provided; you may NOT download/install an older JDK (verification
  checks that the compiled classes target Java 17+ bytecode, and the build must run on JDK 21).
- Gradle: use the wrapper (`./gradlew`) after pointing it at a Gradle version that supports JDK 21 (8.x), or a downloaded Gradle 8.
  Internet (Maven Central, Gradle distributions, JavaFX artifacts, Bio-Formats repositories) is reachable. GRADLE_USER_HOME is set.
- No display: use `xvfb-run -a <cmd>` for anything that initialises JavaFX. `python` (3.12) is available for scripting.
- Deliverable launcher: create `run_qupath.sh` at the workspace root that runs the BUILT QuPath command line, e.g.
  `bash run_qupath.sh script --image sample_data/CMU-1-Small-Region.svs my_script.groovy` (verification calls exactly this form
  under xvfb-run). It must use the artifacts built from this tree (e.g. `build/dist/QuPath-0.2.3/bin/QuPath-0.2.3` from
  `./gradlew jpackage`, or an equivalent `./gradlew run`-style launcher), never the official release binaries.
EON
