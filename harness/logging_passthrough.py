#!/usr/bin/env python3
"""Anthropic -> Anthropic pass-through proxy whose only purpose is to log what Claude Code actually sends.

Why: the gateway rejects a top-level `effort` field ("Extra inputs are not permitted") while Claude Code
has an --effort switch. If the gateway ignores or rejects the effort the CLI sends, every level quietly
collapses into one, and the ablation produces an artefactual null -- the same trap as defects #18 and #28.
So look at what goes over the wire before deciding to run anything.

usage: python3 logging_passthrough.py --port 8899 --upstream <base>/v1/messages --key-file <f>
"""
import argparse, json, sys, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UP = KEY = None
DROP_BETAS = set()
FULLLOG = '/tmp/effort_bodies.jsonl'
LOG = None

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def do_GET(self):
        self.send_response(200); self.send_header("content-type","application/json")
        b=b'{"ok":true}'; self.send_header("content-length",str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        # Log only the effort/thinking-related top-level keys, never the whole prompt
        # Log the full request body minus the prompt text: otherwise it is invisible which field carries effort.
        # A previous round logged only `thinking`, mistook the title side-query for the low level, and
        slim = {k: v for k, v in body.items() if k not in ("messages", "system", "tools")}
        rec = {"path": self.path,
               "beta": self.headers.get("anthropic-beta"),
               "top_level_keys": sorted(body.keys()),
               "effort": body.get("effort"),
               "thinking": body.get("thinking"),
               "model": body.get("model"),
               "max_tokens": body.get("max_tokens"),
               "stream": body.get("stream"),
               "output_config": body.get("output_config"),
               "metadata": body.get("metadata"),
               "context_management": body.get("context_management"),
               "slim_keys": sorted(slim.keys())}
        print("REQ " + json.dumps(rec, ensure_ascii=False), file=sys.stderr, flush=True)

        hdrs = {"content-type": "application/json", "x-api-key": KEY,
                "anthropic-version": self.headers.get("anthropic-version", "2023-06-01")}
        # This gateway's upstream returns 400 for some beta flags (measured: advisor-tool-2026-03-01),
        # and Claude Code sends them on every request, so *no* `claude -p` call gets through at all --
        # nothing to do with effort. Drop them on demand, keeping the ones that matter (effort-2025-11-24).
        # Note: dropping advisor-tool changes the tool set offered to the model. That is a change to the
        # experimental conditions and must be disclosed.
        bh = self.headers.get("anthropic-beta")
        if bh:
            keep = [x for x in bh.split(",") if x.strip() not in DROP_BETAS]
            dropped = [x for x in bh.split(",") if x.strip() in DROP_BETAS]
            if dropped:
                print("DROPPED_BETA " + ",".join(dropped), file=sys.stderr, flush=True)
            if keep:
                hdrs["anthropic-beta"] = ",".join(keep)
        req = urllib.request.Request(UP, data=raw, method="POST", headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                data = r.read()
                ct = r.headers.get("content-type", "application/json")
                code = r.status
        except urllib.error.HTTPError as e:
            data = e.read(); ct = "application/json"; code = e.code
            print("UPSTREAM_ERR %s %s" % (code, data[:300]), file=sys.stderr, flush=True)
        self.send_response(code)
        self.send_header("content-type", ct)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

def main():
    global UP, KEY
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--drop-betas", default="advisor-tool-2026-03-01",
                    help="comma-separated beta flags to drop before forwarding")
    a = ap.parse_args()
    global DROP_BETAS
    UP = a.upstream; KEY = open(a.key_file).read().strip()
    DROP_BETAS = {x.strip() for x in a.drop_betas.split(",") if x.strip()}
    print("[passthrough] %d -> %s" % (a.port, UP), file=sys.stderr, flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()

if __name__ == "__main__":
    main()
