"""Local fixture only. No networking, authentication, SDK, or model invocation."""
import json
from pathlib import Path
import sys
import time
import uuid

control = Path.cwd() / ".acp-mock-control.json"
scenario = json.loads(control.read_text()).get("scenario", "normal") if control.is_file() else "normal"
journal = Path.cwd() / ".acp-mock-events.jsonl"
session = None


def note(method):
    with journal.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"method": method}) + "\n")


def send(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)


def chunk(text, target=None):
    send({"method": "session/update", "params": {"sessionId": target or session,
         "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}}})


for line in sys.stdin:
    request = json.loads(line)
    method, ident = request.get("method"), request.get("id")
    note(method or "client_response")
    if method == "initialize":
        send({"id": ident, "result": {"protocolVersion": True if scenario == "bad_protocol" else 1,
              "agentCapabilities": {"loadSession": scenario != "resume_unsupported"}}})
    elif method == "session/new":
        session = "mock-" + uuid.uuid4().hex
        send({"id": ident, "result": {"sessionId": session}})
    elif method == "session/load":
        session = request["params"]["sessionId"]
        if scenario == "resume_failed":
            send({"id": ident, "error": {"code": -32000, "message": "synthetic-private-error-do-not-retain"}})
        else:
            chunk("Old history, not this answer.")
            send({"id": ident, "result": {}})
    elif method == "session/prompt":
        if scenario == "disconnect":
            break
        if scenario == "malformed":
            print("synthetic-private-invalid-json", flush=True)
            break
        if scenario == "oversize":
            print("x" * 70000, flush=True)
            break
        if scenario == "total_limit":
            for _ in range(40):
                chunk("x" * 50000)
            break
        if scenario == "timeout":
            time.sleep(60)
            break
        if scenario == "session_mismatch":
            chunk("Wrong session", "unrelated-session")
            break
        if scenario == "partial":
            chunk("Incomplete text")
            break
        if scenario == "permission":
            send({"id": "permission-1", "method": "session/request_permission", "params": {
                "sessionId": session, "toolCall": {"toolCallId": "fixture-tool", "title": "Mock request"},
                "options": [{"optionId": "allow", "kind": "allow_always", "name": "Allow"}]}})
            response = json.loads(sys.stdin.readline())
            assert response["result"]["outcome"]["outcome"] == "cancelled"
            note("permission_denied")
        if scenario == "forbidden_request":
            send({"id": "file-1", "method": "fs/read_text_file", "params": {"sessionId": session, "path": "unavailable"}})
            response = json.loads(sys.stdin.readline())
            assert "error" in response
            note("capability_denied")
            continue
        if scenario == "stderr":
            print("synthetic-private-stderr-never-retain", file=sys.stderr, flush=True)
        chunk("Synthetic mock answer.")
        send({"id": ident, "result": {"stopReason": "max_tokens" if scenario == "incomplete" else "end_turn"}})
    elif method == "session/cancel":
        break
