#!/usr/bin/env python3
"""Quantify a defect in diff_stats: if the agent commits by itself, `git diff --cached HEAD` is always
empty and the patch size is recorded as 0. The correct baseline is the first (snapshot) commit.
This script only measures; it changes no data."""
import json, glob, os, subprocess
def sh(ws,*a):
    return subprocess.run(["git",*a],cwd=ws,capture_output=True,text=True).stdout
rows=[]
for d in sorted(glob.glob("runs/*/*/")):
    ws=os.path.join(d,"workspace")
    if not os.path.isdir(os.path.join(ws,".git")): continue
    try: r=json.load(open(d+"results.json"))
    except Exception: continue
    base=sh(ws,"rev-list","--max-parents=0","HEAD").split()
    if not base: continue
    ns=sh(ws,"diff","--numstat",base[0],"HEAD")
    add=sum(int(l.split("\t")[0]) for l in ns.strip().splitlines()
            if l.split("\t")[0].isdigit())
    rec=(r.get("diff") or {}).get("lines_added")
    if rec is None: rec=0
    if add and abs(add-rec)>0:
        rows.append((d.rstrip("/").replace("runs/",""), r.get("model"), rec, add))
print("runs whose recorded size differs from the baseline definition: %d" % len(rows))
print("%-46s %-14s %-9s %s" % ("run","model","recorded","baseline"))
for x in sorted(rows,key=lambda t:-(t[3]-t[2]))[:15]:
    print("%-46s %-14s %-9s %s" % x)
