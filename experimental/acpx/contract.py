"""Original, mock-only ACP contract experiment; not a production provider adapter."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import sqlite3
import subprocess
import sys
import threading
import time

MAX_FRAME = 65536
MAX_OUTPUT = 1024 * 1024
MAX_PROMPT = 16384
MOCK_AGENT = Path(__file__).resolve().with_name("mock_agent.py")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def opaque(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and all(ord(c) >= 32 for c in value)


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class Scope:
    project: str
    account: str = "mock:no-account"
    route: str = "mock-acp"

    def normalized(self):
        project = Path(self.project)
        if not project.is_absolute() or not project.is_dir():
            raise ContractError("An existing absolute project directory is required")
        if self.route != "mock-acp" or not opaque(self.account) or not self.account.startswith("mock:"):
            raise ContractError("This experiment accepts only mock routes and local mock account tags")
        return {"project": os.path.normcase(str(project.resolve())), "account": self.account, "route": self.route}


@dataclass(frozen=True)
class MockCommand:
    executable: str
    agent: str
    executable_sha256: str
    agent_sha256: str

    @classmethod
    def reviewed(cls):
        exe = Path(sys.executable).resolve()
        return cls(str(exe), str(MOCK_AGENT), digest(exe.read_bytes()), digest(MOCK_AGENT.read_bytes()))

    def validate(self):
        executable, agent = Path(self.executable), Path(self.agent)
        if not executable.is_absolute() or not agent.is_absolute():
            raise ContractError("Reviewed executable and mock agent paths must be absolute")
        executable, agent = executable.resolve(), agent.resolve()
        if executable != Path(sys.executable).resolve() or agent != MOCK_AGENT:
            raise ContractError("Only the current Python executable and bundled mock agent are allowed")
        if digest(executable.read_bytes()) != self.executable_sha256 or digest(agent.read_bytes()) != self.agent_sha256:
            raise ContractError("The reviewed mock command changed")
        return [str(executable), "-I", str(agent)]


def mock_environment():
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ"}
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


class WireError(Exception):
    pass


class Interrupted(WireError):
    pass


class Wire:
    def __init__(self, command, cwd, deadline, cancelled):
        flags = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                 if os.name == "nt" else {"start_new_session": True})
        self.process = subprocess.Popen(command, cwd=cwd, env=mock_environment(), stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **flags)
        self.deadline, self.cancelled = deadline, cancelled
        self.messages, self.stop = queue.Queue(maxsize=32), threading.Event()
        self.threads, self.used, self.sequence = [], 0, 0
        self.session, self.phase = None, "initialize"
        self.answer, self.denied, self.prompt_attempted, self.prompt_written = [], 0, False, False
        self.terminal_response = False
        for name, pipe in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
            thread = threading.Thread(target=self._read, args=(name, pipe), daemon=True)
            self.threads.append(thread)
            thread.start()

    def _read(self, source, pipe):
        while not self.stop.is_set():
            data = pipe.readline(MAX_FRAME + 1)
            while not self.stop.is_set():
                try:
                    self.messages.put((source, data), timeout=0.05)
                    break
                except queue.Full:
                    pass
            if not data:
                return

    def check(self):
        if self.cancelled.is_set():
            raise Interrupted("cancelled")
        if time.monotonic() >= self.deadline:
            raise Interrupted("timeout")

    def send(self, value):
        self.check()
        data = packed(value) + b"\n"
        if len(data) > MAX_FRAME:
            raise WireError("request_size_limit")
        result = queue.Queue(maxsize=1)

        def write():
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
                result.put(True)
            except (OSError, ValueError):
                result.put(False)

        thread = threading.Thread(target=write, daemon=True)
        self.threads.append(thread)
        thread.start()
        while True:
            self.check()
            try:
                if not result.get(timeout=0.025):
                    raise WireError("disconnected")
                return
            except queue.Empty:
                continue

    def event(self):
        while True:
            self.check()
            try:
                source, data = self.messages.get(timeout=0.025)
            except queue.Empty:
                continue
            if not data:
                if source == "stdout":
                    raise WireError("disconnected")
                continue
            self.used += len(data)
            if len(data) > MAX_FRAME or self.used > MAX_OUTPUT:
                raise WireError("output_size_limit")
            if source == "stderr":
                continue  # No raw errors, login material, or stderr retained.
            try:
                event = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                raise WireError("malformed_event") from None
            if not isinstance(event, dict) or event.get("jsonrpc") != "2.0":
                raise WireError("malformed_event")
            return event

    def request(self, method, params):
        self.sequence += 1
        ident = self.sequence
        if method == "session/prompt":
            self.prompt_attempted = True  # A failed/partial write is conservatively ambiguous.
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        if method == "session/prompt":
            self.prompt_written = True
        while True:
            event = self.event()
            if "method" not in event:
                if type(event.get("id")) is not int or event["id"] != ident or ("result" in event) == ("error" in event):
                    raise WireError("unmatched_response")
                if "error" in event:
                    raise WireError("resume_failed" if method == "session/load" else "agent_error")
                if not isinstance(event["result"], dict):
                    raise WireError("malformed_result")
                if method == "session/prompt":
                    self.terminal_response = True
                return event["result"]
            params = event.get("params")
            if not isinstance(params, dict) or self.session is None or params.get("sessionId") != self.session:
                raise WireError("session_identity_mismatch")
            if event["method"] == "session/request_permission" and "id" in event:
                if type(event["id"]) not in (str, int):
                    raise WireError("malformed_event")
                self.denied += 1
                self.send({"jsonrpc": "2.0", "id": event["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                continue
            if "id" in event:
                self.send({"jsonrpc": "2.0", "id": event["id"],
                           "error": {"code": -32601, "message": "Client capability is disabled"}})
                raise WireError("forbidden_client_request")
            update = params.get("update")
            if event["method"] != "session/update" or not isinstance(update, dict):
                raise WireError("unsupported_event")
            kind = update.get("sessionUpdate")
            content = update.get("content")
            if kind not in {"agent_message_chunk", "user_message_chunk"} or not isinstance(content, dict):
                raise WireError("unsupported_event")
            if content.get("type") != "text" or not isinstance(content.get("text"), str):
                raise WireError("unsupported_content")
            if self.phase == "prompt" and kind == "agent_message_chunk":
                self.answer.append(content["text"])
            # session/load history is bounded and checked, but never becomes the new answer.

    def close(self):
        self.stop.set()
        if self.process.poll() is None:
            if self.prompt_attempted and not self.terminal_response and self.session:
                # Best effort only: a notification is not a remote cancellation receipt.
                def cancel():
                    try:
                        self.process.stdin.write(packed({"jsonrpc": "2.0", "method": "session/cancel",
                                                        "params": {"sessionId": self.session}}) + b"\n")
                        self.process.stdin.flush()
                    except (OSError, ValueError):
                        pass
                thread = threading.Thread(target=cancel, daemon=True)
                self.threads.append(thread)
                thread.start()
                thread.join(timeout=0.05)
            if os.name == "nt":
                taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/taskkill.exe"
                subprocess.run([str(taskkill), "/PID", str(self.process.pid), "/T", "/F"],
                               capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if self.process.poll() is None:
                self.process.kill()
        self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=0.2)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                pipe.close()
            except OSError:
                pass  # A dead child can leave an unflushed cancellation write.


class Experiment:
    def __init__(self, state: Path, command: MockCommand):
        self.state, self.command = Path(state), command
        self.state.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (session TEXT PRIMARY KEY, scope TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (request TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    scope TEXT NOT NULL, receipt TEXT NOT NULL, active INTEGER NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.state, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def run(self, scope: Scope, request_id: str, prompt: str, *, opt_in=False,
            session_id=None, timeout=3.0, cancelled=None):
        if opt_in is not True:
            raise ContractError("Explicit opt-in to the reviewed bundled mock command is required")
        command = self.command.validate()
        binding = scope.normalized()
        binding["command"] = {"argv": command, "exe_hash": self.command.executable_sha256,
                              "agent_hash": self.command.agent_sha256}
        scope_key = packed(binding).decode()
        if not opaque(request_id) or (session_id is not None and not opaque(session_id)):
            raise ContractError("Explicit bounded request and session identifiers are required")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_PROMPT:
            raise ContractError("Prompt exceeds the bounded text contract")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.05 <= timeout <= 30:
            raise ContractError("Timeout must be between 0.05 and 30 seconds")
        fingerprint = digest(packed({"scope": binding, "session": session_id, "prompt_hash": digest(prompt.encode())}))
        receipt = {"status": "in_progress", "request_id": request_id, "session_id": session_id,
                   "prompt_attempted": False, "prompt_written": False, "permissions_denied": 0,
                   "answer": "", "experimental": True, "transport": "bundled_mock_acp",
                   "account_authenticated": False, "remote_cancellation_verified": False}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT fingerprint, receipt FROM attempts WHERE request=?", (request_id,)).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise ContractError("Request key already binds different inputs")
                return {**json.loads(prior[1]), "duplicate": True}
            if db.execute("SELECT 1 FROM attempts WHERE scope=? AND active=1", (scope_key,)).fetchone():
                raise ContractError("An unresolved attempt owns this exact scope; inspect before new work")
            if session_id is not None:
                saved = db.execute("SELECT scope FROM sessions WHERE session=?", (session_id,)).fetchone()
                if saved is None or saved[0] != scope_key:
                    raise ContractError("Session does not match exact project, account, route, and command")
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,1)", (request_id, fingerprint, scope_key, json.dumps(receipt)))
        wire = None
        try:
            cancelled = cancelled or threading.Event()
            if cancelled.is_set():
                raise Interrupted("cancelled")
            command = self.command.validate()  # Recheck after durable admission, immediately before launch.
            wire = Wire(command, binding["project"], time.monotonic() + timeout, cancelled)
            initialized = wire.request("initialize", {"protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                "clientInfo": {"name": "review-hub-mock-contract", "version": "0.1"}})
            if type(initialized.get("protocolVersion")) is not int or initialized["protocolVersion"] != 1:
                raise WireError("incompatible_protocol")
            if session_id is not None:
                capabilities = initialized.get("agentCapabilities")
                if not isinstance(capabilities, dict) or capabilities.get("loadSession") is not True:
                    raise WireError("resume_unsupported")
                wire.session, wire.phase = session_id, "load"
                wire.request("session/load", {"sessionId": session_id, "cwd": binding["project"], "mcpServers": []})
            else:
                created = wire.request("session/new", {"cwd": binding["project"], "mcpServers": []})
                session_id = created.get("sessionId")
                if not opaque(session_id):
                    raise WireError("malformed_session_id")
                with self.connect() as db:
                    try:
                        db.execute("INSERT INTO sessions VALUES(?,?)", (session_id, scope_key))
                    except sqlite3.IntegrityError:
                        raise WireError("duplicate_session_id") from None
                wire.session = session_id
            receipt["session_id"] = session_id
            wire.phase = "prompt"
            # Persist uncertainty before crossing the write boundary. A host death
            # must not leave a durable receipt falsely asserting no attempted send.
            receipt.update(prompt_attempted=True, prompt_written=None)
            with self.connect() as db:
                db.execute("UPDATE attempts SET receipt=? WHERE request=?", (json.dumps(receipt), request_id))
            final = wire.request("session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]})
            if final.get("stopReason") != "end_turn" or not "".join(wire.answer).strip():
                raise WireError("incomplete_final_response")
            receipt.update(status="returned", answer="".join(wire.answer), reason="end_turn")
        except (WireError, OSError) as error:
            attempted = wire is not None and wire.prompt_attempted
            status = "failed" if wire is not None and wire.terminal_response else ("delivery_unknown" if attempted else "blocked")
            receipt.update(status=status,
                           reason=str(error) if isinstance(error, WireError) else "local_transport_error")
        except BaseException:
            receipt.update(status="delivery_unknown" if wire is not None and wire.prompt_attempted else "blocked",
                           reason="host_interrupted")
            raise
        finally:
            active = 0
            if wire is not None:
                receipt.update(prompt_attempted=wire.prompt_attempted, prompt_written=wire.prompt_written,
                               permissions_denied=wire.denied, response_received=wire.terminal_response)
                try:
                    wire.close()
                    receipt["cleanup_status"] = "closed"
                except (OSError, subprocess.TimeoutExpired):
                    receipt["cleanup_status"] = "unverified"
                    active = 1  # Do not admit another owner when local cleanup is uncertain.
            # An abrupt host death leaves active=1. Never assume it did not send.
            with self.connect() as db:
                db.execute("UPDATE attempts SET receipt=?,active=? WHERE request=?", (json.dumps(receipt), active, request_id))
        return receipt
