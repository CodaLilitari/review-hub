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
            raise ValueError("Each model/mode needs its observed effort options; use default if no adjustable control is exposed")
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


def validate_fallback_observation(value, catalog, model, effort):
    """Validate an app coordinator's scoped evidence, never infer it from prose."""
    fields = {"primary_model", "primary_effort", "target_model", "target_effort", "workspace",
              "scope", "state", "enabled", "selected", "selected_model", "selected_effort",
              "observed_at", "evidence"}
    if not isinstance(value, dict) or set(value) - fields or catalog["source"] != "observed_app":
        raise ValueError("Conditional app fallback needs a structured exact-control or provider-request observation")
    result = {key: text(value.get(key), "fallback " + key, 4000 if key == "evidence" else 300)
              for key in ("primary_model", "primary_effort", "target_model", "target_effort", "workspace",
                          "scope", "state", "observed_at", "evidence")}
    primary = (result["primary_model"], result["primary_effort"])
    if primary != (result["target_model"], result["target_effort"]) or primary == (model, effort):
        raise ValueError("Fallback evidence must target the exact unavailable primary model and effort")
    try:
        observed = datetime.fromisoformat(result["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError()
        fresh = time.time() - FRESH_SECONDS <= observed.timestamp() <= time.time() + 30
    except (ValueError, TypeError, OverflowError):
        fresh = False
    if not fresh:
        raise ValueError("Refresh the exact primary control/request observation before conditional fallback")
    if observed.timestamp() + 0.000001 < catalog["checked_at"]:
        raise ValueError("Fallback evidence predates the latest catalog observation; recheck the primary for this catalog")
    if result["scope"] == "exact_control":
        if result["state"] != "disabled" or value.get("enabled") is not False or value.get("selected") is not False:
            raise ValueError("An enabled, selected or ambiguous primary control cannot establish fallback unavailability")
        if "selected_model" in value or "selected_effort" in value:
            raise ValueError("Exact-control fallback cannot mix provider-request selection evidence")
        if any(m["id"] == primary[0] and primary[1] in m["efforts"] for m in catalog["models"]):
            raise ValueError("Disabled-control evidence contradicts the account-accessible catalog; inspect the actual control")
        result.update(enabled=False, selected=False)
    elif result["scope"] == "provider_request":
        selected = (value.get("selected_model"), value.get("selected_effort"))
        if result["state"] not in {"unavailable", "limit_reached"} or selected != primary:
            raise ValueError("Provider fallback needs an explicit unavailable/limit error from a request with the primary selected")
        if "enabled" in value or "selected" in value:
            raise ValueError("Provider-request fallback cannot mix picker-control evidence")
        result.update(selected_model=primary[0], selected_effort=primary[1])
    else:
        raise ValueError("Menu, ancestor, hidden text, history or browser errors cannot establish exact-model fallback")
    return result


def normalize_selection_policy(value):
    fields = {"primary_model", "primary_effort", "fallback_model", "fallback_effort", "workspace"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("App selection policy needs exact primary/fallback model and effort plus workspace")
    result = {key: text(value[key], "selection policy " + key, 300) for key in fields}
    if (result["primary_model"], result["primary_effort"]) == (result["fallback_model"], result["fallback_effort"]):
        raise ValueError("Primary and fallback choices must differ")
    return result


def install_policy_compatibility_fence(connection):
    """Old in-memory workers must not discard or bypass a newly saved policy.

    Existing rows are preserved. These guards cover the shared SQL write paths;
    they are a client compatibility fence, not provider evidence verification.
    """
    statements = []
    valid_choice = """
        json_extract({choice}, '$.policy_contract_version') = 1
        AND json_extract({choice}, '$.selection_policy') = json_extract(c.data, '$.selection_policy')
        AND json_extract({choice}, '$.catalog_fingerprint') = json_extract(c.data, '$.fingerprint')
        AND CASE json_extract({choice}, '$.selection_basis')
          WHEN 'primary' THEN
            json_extract({choice}, '$.model') = json_extract(c.data, '$.selection_policy.primary_model')
            AND json_extract({choice}, '$.effort') = json_extract(c.data, '$.selection_policy.primary_effort')
          WHEN 'conditional_fallback' THEN
            json_extract({choice}, '$.model') = json_extract(c.data, '$.selection_policy.fallback_model')
            AND json_extract({choice}, '$.effort') = json_extract(c.data, '$.selection_policy.fallback_effort')
            AND json_extract({choice}, '$.policy_catalog_checked_at') = json_extract(c.data, '$.checked_at')
            AND json_type({choice}, '$.fallback_observation') = 'object'
            AND julianday(json_extract({choice}, '$.fallback_observation.observed_at'))
                BETWEEN julianday('now', '-900 seconds') AND julianday('now', '+30 seconds')
          WHEN 'explicit_user_override' THEN
            json_extract({choice}, '$.policy_catalog_checked_at') = json_extract(c.data, '$.checked_at')
            AND length(trim(json_extract({choice}, '$.override_evidence'))) >= 12
          ELSE 0 END
    """
    for event in ("INSERT", "UPDATE"):
        suffix = event.lower()
        statements.append(f"""
            CREATE TRIGGER IF NOT EXISTS model_policy_catalog_{suffix}_v1 BEFORE {event} ON catalogs
            WHEN (json_type(NEW.data, '$.selection_policy') IS NOT NULL OR EXISTS
                  (SELECT 1 FROM catalogs c WHERE c.provider=NEW.provider
                   AND json_type(c.data, '$.selection_policy') IS NOT NULL))
              AND (json_type(NEW.data, '$.selection_policy') IS NOT 'object'
                   OR json_extract(NEW.data, '$.policy_contract_version') IS NOT 1)
            BEGIN SELECT RAISE(ABORT, 'Model policy requires current Hub code; old catalog writes cannot drop it'); END;
            CREATE TRIGGER IF NOT EXISTS model_policy_choice_{suffix}_v1 BEFORE {event} ON choices
            WHEN EXISTS (SELECT 1 FROM catalogs c WHERE c.provider=NEW.provider
                         AND json_type(c.data, '$.selection_policy') IS NOT NULL)
              AND NOT EXISTS (SELECT 1 FROM catalogs c WHERE c.provider=NEW.provider
                              AND ({valid_choice.format(choice='NEW.data')}))
            BEGIN SELECT RAISE(ABORT, 'Model policy requires a current classified choice; use fresh Hub code'); END;
            CREATE TRIGGER IF NOT EXISTS model_policy_consume_{suffix}_v1 BEFORE {event} ON app_uses
            WHEN EXISTS (SELECT 1 FROM catalogs c WHERE c.provider=NEW.provider
                         AND json_type(c.data, '$.selection_policy') IS NOT NULL)
              AND NOT EXISTS (SELECT 1 FROM catalogs c JOIN choices q ON q.provider=c.provider
                              WHERE c.provider=NEW.provider
                              AND NEW.observed_at=json_extract(c.data, '$.checked_at')
                              AND ({valid_choice.format(choice='q.data')}))
            BEGIN SELECT RAISE(ABORT, 'Model policy blocks an unbound or stale choice; use fresh Hub code'); END;
        """)
    connection.executescript("BEGIN IMMEDIATE;" + "\n".join(statements) + "COMMIT;")


class ModelStore:
    def __init__(self, state):
        self.path = Path(state) / "reviewer-models.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("CREATE TABLE IF NOT EXISTS catalogs(provider TEXT PRIMARY KEY, data TEXT NOT NULL);"
                            "CREATE TABLE IF NOT EXISTS choices(provider TEXT PRIMARY KEY, data TEXT NOT NULL);"
                            "CREATE TABLE IF NOT EXISTS app_uses(provider TEXT PRIMARY KEY, observed_at REAL NOT NULL);")
            install_policy_compatibility_fence(c)

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

    def record(self, provider, models, evidence, source, runtime_version="", observed_at=None, runtime_update=None,
               selection_policy=None):
        models = normalize_models(models)
        evidence = text(evidence, "catalog evidence", minimum=12)
        if source not in {"official_cli", "observed_app"}:
            raise ValueError("Catalog source must be official_cli or observed_app")
        if selection_policy is not None:
            if source != "observed_app":
                raise ValueError("Standing app selection policy cannot substitute for CLI discovery")
            selection_policy = normalize_selection_policy(selection_policy)
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
                raise ValueError("Refresh the account's model/mode observation before recording its catalog")
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
            policy = selection_policy if selection_policy is not None else (json.loads(previous[0]).get("selection_policy") if previous else None)
            if policy is not None:
                data["selection_policy"] = policy
                data["policy_contract_version"] = 1
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
        policy = catalog.get("selection_policy") if catalog else None
        policy_recheck = bool(policy and chosen and (
            chosen.get("selection_policy") != policy or
            (chosen.get("selection_basis") != "primary" and chosen.get("policy_catalog_checked_at") != catalog["checked_at"])))
        fallback_recheck = False
        if chosen and chosen.get("fallback_observation"):
            fallback_recheck = not catalog or chosen.get("fallback_catalog_checked_at") != catalog["checked_at"]
            if catalog and not fallback_recheck:
                try:
                    validate_fallback_observation(chosen["fallback_observation"], catalog, chosen["model"], chosen["effort"])
                except ValueError:
                    fallback_recheck = True
        needed = chosen is None or changed or fallback_recheck or policy_recheck
        return {"provider": provider, "catalog": catalog, "selection": chosen,
                "refresh_required": not fresh, "selection_required": needed,
                "app_observation_consumed": consumed,
                "catalog_scope": ("Installed client's account-visible catalog; an older client can omit newer account models. "
                                  "Check runtime_update and refresh after updating; a catalog is not proof of the latest global options."
                                  if catalog and catalog["source"] == "official_cli" else
                                  "Coordinator-recorded signed-in controls or observed absence/provider-managed mode; local descriptors do not verify backend identity. Verify current app state again at the actual send."
                                  if catalog else "No account model/mode observation has been recorded."),
                "reason": "first_use" if chosen is None else "catalog_changed" if changed else "fallback_recheck_required" if fallback_recheck else "selection_policy_recheck_required" if policy_recheck else "unchanged",
                "next": ("Refresh the account's model/mode options and any available thinking controls" if not fresh else
                         "Recheck the exact primary model/effort control or request error before selecting a conditional fallback" if fallback_recheck else
                         "Apply the standing primary policy, or record a verified conditional fallback or current explicit human override" if policy_recheck else
                         "Reapply the user's standing primary policy, or recheck its conditional fallback; ask only before an unapproved choice" if policy and needed else
                         "Ask the user to choose a model or observed provider-managed mode and an available effort setting, then select_model" if needed else
                         "Use the saved local choice; recheck app observations before a manual send. Automated dispatch rechecks availability"),
                "sent": False}

    def select(self, provider, model, effort, catalog_fingerprint, evidence, fallback_observation=None,
               selection_basis=None, override_evidence=None):
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
                raise ValueError("Choose a model/mode and effort setting exposed by this account")
            choice = {"model": model, "effort": effort, "catalog_fingerprint": catalog_fingerprint,
                      "evidence": evidence, "chosen_at": datetime.now(timezone.utc).isoformat()}
            policy = catalog.get("selection_policy")
            if selection_basis not in {None, "primary", "conditional_fallback", "explicit_user_override"}:
                raise ValueError("Invalid model selection_basis")
            if policy:
                primary = (policy["primary_model"], policy["primary_effort"])
                if (model, effort) == primary and selection_basis in {None, "primary"}:
                    selection_basis = "primary"
                elif selection_basis not in {"conditional_fallback", "explicit_user_override"}:
                    raise ValueError("Non-primary selection requires selection_basis=conditional_fallback or explicit_user_override")
                choice.update(selection_policy=policy, policy_catalog_checked_at=catalog["checked_at"], policy_contract_version=1)
            elif selection_basis is not None or fallback_observation is not None or override_evidence is not None:
                raise ValueError("Record the user's structured standing selection policy before a classified model choice")
            if selection_basis == "conditional_fallback":
                if (model, effort) != (policy["fallback_model"], policy["fallback_effort"]):
                    raise ValueError("Conditional selection must be the user's approved fallback")
                if not isinstance(fallback_observation, dict):
                    raise ValueError("Conditional fallback requires structured fallback_observation")
                if (fallback_observation.get("primary_model"), fallback_observation.get("primary_effort")) != primary:
                    raise ValueError("Fallback observation must match the configured primary")
                if fallback_observation.get("workspace") != policy["workspace"]:
                    raise ValueError("Fallback observation must match the configured account workspace")
                choice["fallback_observation"] = validate_fallback_observation(fallback_observation, catalog, model, effort)
                choice["fallback_catalog_checked_at"] = catalog["checked_at"]
            elif fallback_observation is not None:
                raise ValueError("fallback_observation requires selection_basis=conditional_fallback")
            if selection_basis == "explicit_user_override":
                choice["override_evidence"] = text(override_evidence, "current human override evidence", minimum=12)
            elif override_evidence is not None:
                raise ValueError("override_evidence requires selection_basis=explicit_user_override")
            if selection_basis is not None:
                choice["selection_basis"] = selection_basis
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
        """Consume one app control/mode observation before exposing a prepared handoff.

        This claim remains consumed if later file preparation fails. It verifies
        preparation time only; actual sending is still a coordinator action.
        """
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            status = self._status(c, provider)
            selected = self._require(status)
            if status["catalog"]["source"] != "observed_app":
                raise ValueError("App handoffs require a current observation of signed-in controls or their absence/provider-managed mode")
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
