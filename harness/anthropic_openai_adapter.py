#!/usr/bin/env python3
"""Anthropic Messages API  ->  OpenAI chat/completions adapter (standard library only).

Why it exists: the agent in these experiments is Claude Code (`claude -p`), which speaks only the
Anthropic Messages protocol, while gpt-5.6-sol / luna / terra are exposed on that gateway only in
OpenAI form (/openai/v1/chat/completions).
The gateway is a pure forwarding tunnel (only /{path} and /healthz, no registration or configuration
endpoint) and its Anthropic side knows only its own claude-* deployments, so the three models cannot
be mapped in from outside.
The translation layer therefore sits on our side: Claude Code -> this adapter -> gateway /openai -> upstream.

Deliberate trade-off: call the upstream non-streaming, and synthesise the SSE events here.
Claude Code needs a well-formed event sequence, not genuinely token-by-token arrival. Reassembling
tool_call fragments from a stream is where adapters like this usually break (argument JSON split at
arbitrary points, mismatched indices), and a benchmark does not need incremental output.
Trading that risk away is worth it; the cost is waiting for the upstream to answer in full.

Three things must hold, and do (miss one and all 13 tasks return nothing, while looking like a
capability failure of the model):
  1. POST /v1/messages with stream:true
  2. message_start / content_block_start / content_block_delta /
     content_block_stop / message_delta / message_stop
  3. tool_use / tool_result round-trips, with tool_use.id preserved verbatim for pairing

usage:
    python3 anthropic_openai_adapter.py --port 8787 \
        --upstream https://<gw>/openai/v1/chat/completions --key-file <file>
then:
    export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
    export ANTHROPIC_API_KEY=dummy
    claude -p ... --model gpt-5.6-sol
"""
import argparse
import json
import random
import time
import os
import sys
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = None
# Which field carries the output cap; see the note in to_openai. The default keeps the original
# behaviour so the conditions of existing batches do not change.
TOKEN_FIELD = "max_completion_tokens"
API_KEY = None
DEBUG = False
FORCE_MODEL = None   # Claude Code validates --model client-side and rejects an unknown id outright.
                     # So launch it under a name it knows; the adapter substitutes the real upstream model.


def log(*a):
    if DEBUG:
        print("[adapter]", *a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- request translation
def _text_of(content):
    """Anthropic content may be a str or a list of blocks; extract the plain text."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def to_openai(req):
    """Anthropic Messages request -> OpenAI chat/completions request."""
    msgs = []
    sys_prompt = req.get("system")
    if sys_prompt:
        msgs.append({"role": "system", "content": _text_of(sys_prompt)})

    for m in req.get("messages", []):
        role, content = m.get("role"), m.get("content")
        if isinstance(content, str):
            msgs.append({"role": role, "content": content})
            continue

        # assistant turn: text + tool_use -> assistant.content + tool_calls
        if role == "assistant":
            text, calls = "", []
            for b in content:
                if b.get("type") == "text":
                    text += b.get("text", "")
                elif b.get("type") == "tool_use":
                    calls.append({"id": b["id"], "type": "function",
                                  "function": {"name": b["name"],
                                               "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}})
            a = {"role": "assistant", "content": text or None}
            if calls:
                a["tool_calls"] = calls
            msgs.append(a)
            continue

        # user turn: each tool_result becomes its own role:tool message, paired by tool_use_id
        buf = ""
        for b in content:
            if b.get("type") == "tool_result":
                if buf:
                    msgs.append({"role": "user", "content": buf}); buf = ""
                c = b.get("content")
                msgs.append({"role": "tool", "tool_call_id": b.get("tool_use_id"),
                             "content": _text_of(c) if not isinstance(c, str) else c})
            elif b.get("type") == "text":
                buf += b.get("text", "")
        if buf:
            msgs.append({"role": "user", "content": buf})

    out = {"model": req.get("model"), "messages": msgs}
    # Which field carries the output cap differs by provider, and must be measured as honoured, not
    # merely accepted:
    #   gpt-5.6: takes max_completion_tokens only; max_tokens is rejected.
    #   glm-5.3-flash: returns 200 for max_completion_tokens and silently ignores it -- the same context
    #     with a cap of 2000 produced 59,942 tokens in 704s, while max_tokens=2000 gave 25s,
    #     finish=length and exactly 2000.
    #     Wiring GLM up the gpt-5.6 way left every GLM run with no output cap at all.
    if req.get("max_tokens"):
        out[TOKEN_FIELD] = req["max_tokens"]
    if req.get("tools"):
        out["tools"] = [{"type": "function",
                         "function": {"name": t["name"],
                                      "description": t.get("description", ""),
                                      "parameters": t.get("input_schema", {"type": "object"})}}
                        for t in req["tools"]]
        tc = req.get("tool_choice", {})
        if isinstance(tc, dict) and tc.get("type") == "tool" and tc.get("name"):
            out["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}
    return out


STOP_MAP = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens",
            "content_filter": "end_turn", "function_call": "tool_use"}


def to_anthropic(oai, model):
    """OpenAI response -> Anthropic message object."""
    ch = (oai.get("choices") or [{}])[0]
    msg = ch.get("message", {})
    blocks = []
    if msg.get("content"):
        blocks.append({"type": "text", "text": msg["content"]})
    for c in msg.get("tool_calls") or []:
        fn = c.get("function", {})
        try:
            inp = json.loads(fn.get("arguments") or "{}")
        except Exception:
            inp = {"_raw": fn.get("arguments")}
        blocks.append({"type": "tool_use", "id": c.get("id"), "name": fn.get("name"), "input": inp})
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    u = oai.get("usage") or {}
    return {
        "id": oai.get("id", "msg_adapter"), "type": "message", "role": "assistant",
        "model": model, "content": blocks,
        "stop_reason": STOP_MAP.get(ch.get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": u.get("prompt_tokens", 0),
                  "output_tokens": u.get("completion_tokens", 0)},
    }


# This provider returns no rate-limit headers: throttling shows up only as 429, and concurrent runs hit
# it easily. The adapter had no retry, so a single 429 recorded that run_task as infra_error and a batch
# of 13 tasks could end with a handful of valid results. Exponential backoff with jitter, retrying only
# genuinely retryable status codes.
# Send both headers: Azure-style tunnels want api-key, the other gateways want Authorization: Bearer.
RETRY_CODES = {408, 409, 429, 500, 502, 503, 504}
MAX_RETRY = int(os.environ.get("REVIVE_ADAPTER_RETRIES", "5"))


# Preserve the scene of a failure: the debug log keeps only the first 200 bytes of a body, which cannot
# reconstruct the request that hung. With REVIVE_ADAPTER_DUMP_DIR set, a request whose retries are
# exhausted is written out in full, so it can be replayed verbatim and bisected. Failures only.
DUMP_DIR = os.environ.get("REVIVE_ADAPTER_DUMP_DIR")
# Read timeout for one upstream call. Measured: some contexts take 454-820s to return even with a cap
# of 1, sending no bytes meanwhile. The old hardcoded 900s sat right at the measured limit.
UPSTREAM_TIMEOUT = float(os.environ.get("REVIVE_UPSTREAM_TIMEOUT", "1800"))
# Interval between SSE pings sent to Claude Code while waiting for the upstream (see H._stream).
PING_EVERY = float(os.environ.get("REVIVE_ADAPTER_PING_S", "15"))


def _read_body(obj):
    """Read an HTTP response or HTTPError body, transparently un-gzipping it.

    The kimi-k3 gateway gzips responses even when the request does not ask for it; urllib does not
    decompress, so json.loads saw b'\\x1f\\x8b...' and every request failed with UnicodeDecodeError.
    Decompress on either the Content-Encoding header or the gzip magic bytes, so uncompressed upstreams
    (GLM, GPT-5.6) are unaffected.
    """
    raw = obj.read()
    enc = ""
    try:
        enc = (obj.headers.get("Content-Encoding") or "").lower()
    except Exception:  # noqa: BLE001
        pass
    if "gzip" in enc or raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw


def _dump_failed(payload, err):
    if not DUMP_DIR:
        return
    try:
        os.makedirs(DUMP_DIR, exist_ok=True)
        fn = os.path.join(DUMP_DIR, "failed_%d_%d.json" % (int(time.time() * 1000), threading.get_ident()))
        with open(fn, "w") as fh:
            json.dump({"error": repr(err), "payload": payload}, fh)
        print(f"[adapter] failed request saved to {fn}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[adapter] could not save failed request: {e!r}", file=sys.stderr, flush=True)


def call_upstream(payload):
    try:
        return _call_upstream(payload)
    except Exception as e:
        _dump_failed(payload, e)
        raise


def _call_upstream(payload):
    body = json.dumps(payload).encode()
    last = None
    for attempt in range(MAX_RETRY + 1):
        r = urllib.request.Request(UPSTREAM, data=body, method="POST", headers={
            "content-type": "application/json", "api-key": API_KEY,
            "Authorization": "Bearer " + API_KEY})
        try:
            with urllib.request.urlopen(r, timeout=UPSTREAM_TIMEOUT) as resp:
                return json.loads(_read_body(resp))
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in RETRY_CODES or attempt == MAX_RETRY:
                raise
            detail = ""
            try:
                detail = _read_body(e)[:200].decode("utf-8", "replace")
            except Exception:
                pass
            wait = min(60.0, 2.0 ** attempt) * (1.0 + 0.3 * random.random())
            print(f"[adapter] upstream {e.code}, retry {attempt+1}/{MAX_RETRY} "
                  f"after {wait:.1f}s {detail}", file=sys.stderr, flush=True)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if attempt == MAX_RETRY:
                raise
            wait = min(60.0, 2.0 ** attempt) * (1.0 + 0.3 * random.random())
            print(f"[adapter] upstream connection error {e}, retrying after {wait:.1f}s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
    raise last


# ---------------------------------------------------------------- SSE synthesis
def sse(ev, data):
    return f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def body_events(m):
    """Everything after message_start: content blocks, message_delta (with full usage), message_stop.

    input_tokens goes in message_delta: on the streaming path message_start is sent before the upstream
    answers, when the input size is still unknown. Measured: Claude Code accounts from the input_tokens
    in message_delta (a fake upstream sending 0 then 1234 yields usage.input_tokens=1234).
    """
    for i, b in enumerate(m["content"]):
        if b["type"] == "text":
            yield sse("content_block_start",
                      {"type": "content_block_start", "index": i,
                       "content_block": {"type": "text", "text": ""}})
            if b.get("text"):
                yield sse("content_block_delta",
                          {"type": "content_block_delta", "index": i,
                           "delta": {"type": "text_delta", "text": b["text"]}})
        else:  # tool_use: input must arrive via input_json_delta; the opening block carries an empty object
            yield sse("content_block_start",
                      {"type": "content_block_start", "index": i,
                       "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
            yield sse("content_block_delta",
                      {"type": "content_block_delta", "index": i,
                       "delta": {"type": "input_json_delta",
                                 "partial_json": json.dumps(b.get("input", {}), ensure_ascii=False)}})
        yield sse("content_block_stop", {"type": "content_block_stop", "index": i})
    yield sse("message_delta",
              {"type": "message_delta",
               "delta": {"stop_reason": m["stop_reason"], "stop_sequence": None},
               "usage": {"input_tokens": m["usage"]["input_tokens"],
                         "output_tokens": m["usage"]["output_tokens"]}})
    yield sse("message_stop", {"type": "message_stop"})


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _trace(self, body=b""):
        log("REQ", self.command, self.path,
            "hdrs=", {k.lower(): v for k, v in self.headers.items()
                      if k.lower() in ("anthropic-beta", "anthropic-version", "content-type")},
            "body=", body[:200])

    def do_GET(self):
        self._trace()
        if self.path.rstrip("/") in ("/healthz", ""):
            self._json(200, {"ok": True, "force_model": FORCE_MODEL, "upstream": UPSTREAM,
                             "token_field": TOKEN_FIELD})
        else:
            self._json(404, {"error": {"type": "not_found", "message": self.path}})

    def do_POST(self):
        n0 = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n0) if n0 else b""
        self._trace(raw)
        # helper endpoints such as count_tokens: return a well-formed estimate so Claude Code does not fail
        if self.path.rstrip("/").endswith("/v1/messages/count_tokens"):
            try:
                rq = json.loads(raw or b"{}")
            except Exception:
                rq = {}
            approx = max(1, len(json.dumps(rq.get("messages", []))) // 4)
            return self._json(200, {"input_tokens": approx})
        if "/v1/messages" not in self.path:
            return self._json(404, {"error": {"type": "not_found", "message": self.path}})
        try:
            req = json.loads(raw or b"{}")
        except Exception as e:
            return self._json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": str(e)}})

        model = FORCE_MODEL or req.get("model", "?")
        if FORCE_MODEL:
            req["model"] = FORCE_MODEL
        if req.get("stream"):
            return self._stream(req, model)
        try:
            oai = call_upstream(to_openai(req))
            m = to_anthropic(oai, model)
            log(model, "stop=", m["stop_reason"], "blocks=", [b["type"] for b in m["content"]],
                "in=%d out=%d" % (m["usage"]["input_tokens"], m["usage"]["output_tokens"]))
        except urllib.error.HTTPError as e:
            detail = _read_body(e)[:400].decode("utf-8", "replace")
            log("upstream HTTP", e.code, detail)
            return self._json(e.code if e.code in (400, 401, 403, 404, 429) else 502,
                              {"type": "error",
                               "error": {"type": "api_error", "message": f"upstream {e.code}: {detail}"}})
        except Exception as e:  # noqa: BLE001
            log("upstream error", repr(e))
            return self._json(502, {"type": "error", "error": {"type": "api_error", "message": repr(e)}})
        return self._json(200, m)

    def _chunk(self, data):
        self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
        self.wfile.flush()

    def _stream(self, req, model):
        """Streaming path: send message_start, ping while waiting, then the body once upstream answers.

        Why: the streaming path used to write no SSE at all until the upstream had fully answered.
        One provider takes 8-14 minutes on some contexts (a streaming trace shows headers and the first
        chunk within 1-3s, so it is slow, not hung). Claude Code, receiving nothing, gave up and resent
        ten times before reporting "Request timed out". Five tasks in the GLM batch produced nothing twice each.
        Measured: with pings arriving, Claude Code waits the full 480s, sends one request, and both the
        result and the accounting are correct.

        When the upstream finally fails the response has already begun, so an HTTP 5xx is no longer
        possible: send an SSE error event instead -- timeouts and 5xx as overloaded_error (retryable),
        429 as rate_limit_error, everything else not retryable.
        """
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "keep-alive")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        payload = to_openai(req)
        box = {}

        def work():
            try:
                box["m"] = to_anthropic(call_upstream(payload), model)
            except BaseException as e:  # noqa: BLE001
                box["err"] = e

        th = threading.Thread(target=work, daemon=True)
        th.start()
        waited = 0.0
        try:
            self._chunk(sse("message_start", {"type": "message_start", "message": {
                "id": "msg_adapter", "type": "message", "role": "assistant", "model": model,
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0}}}))
            while True:
                th.join(PING_EVERY)
                if not th.is_alive():
                    break
                waited += PING_EVERY
                self._chunk(sse("ping", {"type": "ping"}))
            if "m" in box:
                m = box["m"]
                # Per-turn usage has to be logged here: Claude Code's trajectory keeps only the usage from
                # message_start, whose output is always 0, which is why it was impossible to tell whether
                # any single GLM turn had exceeded 64K output tokens.
                log(model, "stop=", m["stop_reason"], "blocks=", [b["type"] for b in m["content"]],
                    "waited~%ds" % waited,
                    "in=%d out=%d" % (m["usage"]["input_tokens"], m["usage"]["output_tokens"]))
                for ev in body_events(m):
                    self._chunk(ev)
            else:
                e = box.get("err")
                code = getattr(e, "code", None)
                detail = ""
                if isinstance(e, urllib.error.HTTPError):
                    try:
                        detail = _read_body(e)[:400].decode("utf-8", "replace")
                    except Exception:  # noqa: BLE001
                        pass
                if code == 429:
                    etype = "rate_limit_error"
                elif code is None or code in RETRY_CODES:
                    etype = "overloaded_error"
                else:
                    etype = "invalid_request_error"
                log("upstream error (stream)", etype, repr(e), detail)
                self._chunk(sse("error", {"type": "error", "error": {
                    "type": etype, "message": f"upstream {code or ''} {e!r} {detail}".strip()}}))
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            log("client disconnected while waiting upstream, waited~%ds" % waited)


def main():
    global UPSTREAM, API_KEY, DEBUG
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--force-model", default=None,
                    help="ignore the request's model and always use this upstream model (works around Claude Code's client-side check)")
    ap.add_argument("--token-field", default="max_completion_tokens",
                    choices=["max_completion_tokens", "max_tokens"],
                    help="which upstream field carries Claude Code's max_tokens; choose by measuring which one the upstream honours")
    a = ap.parse_args()
    global FORCE_MODEL, TOKEN_FIELD
    TOKEN_FIELD = a.token_field
    UPSTREAM, DEBUG, FORCE_MODEL = a.upstream, a.debug, a.force_model
    API_KEY = open(a.key_file).read().strip()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    srv.daemon_threads = True
    print(f"[adapter] listening on http://127.0.0.1:{a.port} -> {UPSTREAM}", file=sys.stderr, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
