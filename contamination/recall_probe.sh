#!/bin/bash
# Memorisation probe: no tools, one turn. Can the model write the deleted module from memory?
cd "${REVIVE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"/contamination/recall
PROMPT='Reproduce, verbatim and in full, the file deepimpute/multinet.py from the GitHub repository lanagarmire/deepimpute (the DeepImpute single-cell imputation package, version 1.2, 2019-2022). Output only the Python source code of that file, nothing else. Do not use any tools.'
for m in fable sonnet haiku; do
  env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT timeout 600 claude -p "$PROMPT" --model $m --max-turns 1 --tools "" --output-format json > recall_${m}.json 2> recall_${m}.err
  python3 -c "
import json,re; d=json.load(open('recall_${m}.json')); t=d.get('result','')
m=re.search(r'\`\`\`(?:python)?\n(.*?)\`\`\`', t, re.S); src=m.group(1) if m else t
open('recall_${m}.py','w').write(src); print('${m}', 'lines', src.count(chr(10)), 'cost', d.get('total_cost_usd'))"
done
