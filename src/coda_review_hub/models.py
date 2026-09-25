"""Account-visible model catalogs and explicit user choices, outside Git.

Application versions are evidence, not compatibility allowlists. Catalog changes
invalidate confirmation; unchanged catalogs preserve the user's chosen model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

FRESH_SECONDS = 900


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def text(value, name, maximum=4000, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"{name} must contain {minimum}..{maximum} characters")
    if any(ord(c) < 32 for c in value) or "\x7f" in value:
        raise ValueError(f"{name} contains control characters")
    return value.strip()


def normalize_models(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 200:
        raise ValueError("Report 1..200 account-accessible models, not a marketing list")
    result, seen = [], set()
    for item in values:
        if not isinstance(item, dict) or set(item) - {"id", "label", "efforts", "resolved_id"}:
            raise ValueError("Model entries accept id, label, efforts, and resolved_id only")
        model = text(item.get("id"), "model id", 200)
        if model in seen:
            raise ValueError("Model IDs must be unique")
        seen.add(model)
        levels = item.get("efforts")
        if not isinstance(levels, list) or not 1 <= len(levels) <= 32:
            raise ValueError("Each model needs its observed effort options; use default if not adjustable")
        efforts = [text(x, "effort", 100) for x in levels]
        if len(set(efforts)) != len(efforts):
            raise ValueError("Effort options must be unique")
        result.append({"id": model, "label": text(item.get("label", model), "model label", 300),
                       "efforts": sorted(efforts), "resolved_id": text(item.get("resolved_id", model), "resolved model id", 200)})
    return sorted(result, key=lambda x: x["id"])


def runtime_advisory(value):
    """Keep bounded release metadata as advice, never model entitlement proof."""
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("status") not in {"checked", "unavailable"}:
        raise ValueError("Invalid runtime update observation")
    result = {"status": value["status"]}
    for key in ("installed_version", "latest_version", "checked_at", "source", "guidance"):
        if value.get(key) is not None:
            result[key] = text(value[key], "runtime update " + key, 1000)
    available = value.get("update_available")
    if available is not None and type(available) is not bool:
        raise ValueError("Runtime update availability must be boolean or unknown")
    result["update_available"] = available
    return result


class ModelStore:
    def __init__(self, state):
        self.path = Path(state) / "reviewer-models.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("CREATE TABLE IF NOT EXISTS catalogs(provider TEXT PRIMARY KEY, data TEXT NOT NULL);"
                            "CREATE TABLE IF NOT EXISTS choices(provider TEXT PRIMARY KEY, data TEXT NOT NULL);"
                            "CREATE TABLE IF NOT EXISTS app_uses(provider TEXT PRIMARY KEY, observed_at REAL NOT NULL);")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=20)
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record(self, provider, models, evidence, source, runtime_version="", observed_at=None, runtime_update=None):
        models = normalize_models(models)
        evidence = text(evidence, "catalog evidence", minimum=12)
        if source not in {"official_cli", "observed_app"}:
            raise ValueError("Catalog source must be official_cli or observed_app")
        if not isinstance(runtime_version, str) or len(runtime_version) > 200:
            raise ValueError("Invalid runtime version observation")
        checked = time.time()
        if observed_at is not None:
            try:
                date = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                if date.tzinfo is None:
                    raise ValueError()
                checked = date.timestamp()
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Catalog observation needs a timezone-qualified timestamp") from None
            if not time.time() - FRESH_SECONDS <= checked <= time.time() + 30:
                raise ValueError("Refresh the account's model picker before recording its catalog")
        # Version/labels can change without changing the user's available choices.
        signature = [{"id": m["id"], "efforts": m["efforts"], "resolved_id": m["resolved_id"]} for m in models]
        fingerprint = hashlib.sha256(canonical(signature).encode()).hexdigest()
        data = {"provider": provider, "models": models, "fingerprint": fingerprint,
                "checked_at": checked, "source": source, "evidence": evidence,
                "runtime_version": runtime_version}
        advisory = runtime_advisory(runtime_update)
        if advisory is not None:
            data["runtime_update"] = advisory
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            previous = c.execute("SELECT data FROM catalogs WHERE provider=?", (provider,)).fetchone()
            if previous and json.loads(previous[0])["checked_at"] > checked:
                raise ValueError("A newer account catalog observation is already saved; do not replace it with an older one")
            c.execute("INSERT OR REPLACE INTO catalogs VALUES (?,?)", (provider, canonical(data)))
        return self.status(provider)

    def status(self, provider):
        with self.connect() as c:
            c.execute("BEGIN")
            return self._status(c, provider)

    def _status(self, c, provider):
        row = c.execute("SELECT data FROM catalogs WHERE provider=?", (provider,)).fetchone()
        choice = c.execute("SELECT data FROM choices WHERE provider=?", (provider,)).fetchone()
        used = c.execute("SELECT observed_at FROM app_uses WHERE provider=?", (provider,)).fetchone()
        catalog = json.loads(row[0]) if row else None
        chosen = json.loads(choice[0]) if choice else None
        consumed = bool(catalog and catalog["source"] == "observed_app" and used and catalog["checked_at"] <= used[0])
        fresh = bool(catalog and catalog["checked_at"] >= time.time() - FRESH_SECONDS and not consumed)
        changed = bool(catalog and chosen and catalog["fingerprint"] != chosen["catalog_fingerprint"])
        needed = chosen is None or changed
        return {"provider": provider, "catalog": catalog, "selection": chosen,
                "refresh_required": not fresh, "selection_required": needed,
                "app_observation_consumed": consumed,
                "catalog_scope": ("Installed client's account-visible catalog; an older client can omit newer account models. "
                                  "Check runtime_update and refresh after updating; a catalog is not proof of the latest global options."
                                  if catalog and catalog["source"] == "official_cli" else
                                  "Coordinator-observed app picker; verify the current picker again at the actual send."),
                "reason": "first_use" if chosen is None else "catalog_changed" if changed else "unchanged",
                "next": ("Refresh the account's available models and thinking levels" if not fresh else
                         "Ask the user to choose a model and thinking level, then select_model" if needed else
                         "Use the saved choice; automated dispatch rechecks availability before sending"),
                "sent": False}

    def select(self, provider, model, effort, catalog_fingerprint, evidence):
        evidence = text(evidence, "user choice evidence", minimum=12)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT data FROM catalogs WHERE provider=?", (provider,)).fetchone()
            if not row:
                raise ValueError("Refresh models before asking the user to select one")
            catalog = json.loads(row[0])
            used = c.execute("SELECT observed_at FROM app_uses WHERE provider=?", (provider,)).fetchone()
            if (catalog["checked_at"] < time.time() - FRESH_SECONDS
                    or (catalog["source"] == "observed_app" and used and catalog["checked_at"] <= used[0])):
                raise ValueError("Model catalog expired; refresh before saving a choice")
            if catalog_fingerprint != catalog["fingerprint"]:
                raise ValueError("Available choices changed while the user was choosing; present the new catalog")
            match = next((m for m in catalog["models"] if m["id"] == model), None)
            if not match or effort not in match["efforts"]:
                raise ValueError("Choose a model and thinking level exposed by this account")
            choice = {"model": model, "effort": effort, "catalog_fingerprint": catalog_fingerprint,
                      "evidence": evidence, "chosen_at": datetime.now(timezone.utc).isoformat()}
            c.execute("INSERT OR REPLACE INTO choices VALUES (?,?)", (provider, canonical(choice)))
        return self.status(provider)

    def require(self, provider):
        status = self.status(provider)
        return self._require(status)

    @staticmethod
    def _require(status):
        if status["refresh_required"] or status["selection_required"]:
            raise ValueError(f"{status['provider']}: {status['next']}. Inspect model_status/refresh_models; no request was sent.")
        return status["selection"]

    @contextmanager
    def guard_selection(self, provider, *, expected=None):
        """Serialize a local dispatch claim with catalog/choice changes.

        Acquire this BEFORE the jobs database. The caller commits its local job
        claim before leaving; later user changes apply to subsequent jobs.
        No network/discovery operation belongs inside this transaction.
        """
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            status = self._status(c, provider)
            selected = self._require(status)
            if expected is not None and any(selected[key] != expected.get(key)
                                           for key in ("model", "effort", "catalog_fingerprint")):
                raise ValueError("Model choices changed after preparation; ask the user before a new dispatch")
            yield selected

    def claim_app_selection(self, provider):
        """Consume one picker observation before exposing a prepared handoff.

        This claim remains consumed if later file preparation fails. It verifies
        preparation time only; actual sending is still a coordinator action.
        """
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            status = self._status(c, provider)
            selected = self._require(status)
            if status["catalog"]["source"] != "observed_app":
                raise ValueError("App handoffs require a current observed app picker")
            checked_at = status["catalog"]["checked_at"]
            c.execute("INSERT OR REPLACE INTO app_uses VALUES (?,?)", (provider, checked_at))
        return {**selected, "catalog_checked_at": checked_at}


CATALOG_RUNNER = r'''
import hashlib, importlib.util, json, pathlib, sys
path=pathlib.Path(sys.argv[1])
if hashlib.sha256(path.read_bytes()).hexdigest() != sys.argv[2]:
    raise SystemExit("Reviewed helper changed before catalog discovery")
spec=importlib.util.spec_from_file_location("review_hub_catalog_helper",path)
helper=importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
probe=getattr(helper,"discover_models",None)
if not callable(probe):
    raise SystemExit("This helper does not support non-generating model discovery; update the adapter")
try:
    result=probe()
except Exception:
    raise SystemExit("Model discovery failed; inspect authentication and required CLI capabilities without enabling API billing")
print(json.dumps(result,ensure_ascii=True))
'''


def discover(pin):
    """Run only a reviewed helper's metadata probe, never a user/model prompt."""
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "TEMP", "TMP", "COMSPEC", "PATHEXT"}}
    command = [sys.executable, "-I", "-c", CATALOG_RUNNER, pin["path"], pin["sha256"]]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, shell=False, **flags)
    try:
        stdout, stderr = proc.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run([str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/taskkill.exe"),
                            "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=20,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        proc.kill()
        proc.communicate(timeout=20)
        raise ValueError("Model discovery timed out; no review packet was sent") from None
    if proc.returncode or stderr.strip() or len(stdout) > 1024 * 1024:
        raise ValueError("Model discovery failed; check the signed-in CLI and adapter capabilities. No review was sent")
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise ValueError("Model discovery returned an invalid catalog") from None
    if not isinstance(result, dict) or result.get("source") != "official_cli":
        raise ValueError("Automated discovery requires an official account CLI catalog")
    return result
