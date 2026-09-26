"""Single-process durable channel inbox. Interrupted jobs require review, never blind replay."""

import hashlib
import hmac
import json
import re
import threading
import time
from uuid import uuid4
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import Principal
from .scenarios import DescriptionRequest, describe
from .models import Decision, RunRequest
from .order_designer import compile_orders, propose_orders, OrderDesignSpec
from .designer import ScenarioRequest


class BackgroundDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    approve: bool
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Channels:
    def __init__(self, settings, agent, planner, voice):
        self.settings, self.agent, self.planner, self.voice = settings, agent, planner, voice
        self.store = agent.store
        self.http = httpx.Client(timeout=30, follow_redirects=False)
        self.stop = threading.Event()
        self.thread = None
        self.links = {
            phone: Principal.model_validate(p)
            for phone, p in json.loads(settings.whatsapp_links_json).items()
        }
        for phone, p in self.links.items():
            if not re.fullmatch(r"[1-9][0-9]{6,14}", phone) or p.tenant_id not in agent.tenants:
                raise ValueError("Invalid server-owned WhatsApp link")
        if not re.fullmatch(r"v[0-9]+\.0", settings.whatsapp_graph_version):
            raise ValueError("Invalid Meta Graph API version")
        self.store.query("""CREATE TABLE IF NOT EXISTS channel_jobs (
          id TEXT PRIMARY KEY, source TEXT, external_id TEXT UNIQUE, tenant TEXT, actor TEXT,
          role TEXT, sender TEXT, payload TEXT, state TEXT, result TEXT, created REAL, reply_state TEXT)""")
        self.store.query(
            "UPDATE channel_jobs SET state='needs_attention',payload='{}',result=? WHERE state='processing'",
            (json.dumps({"message": "Worker interrupted; inspect Activity before resubmitting"}),),
        )
        self.store.query("UPDATE channel_jobs SET reply_state='uncertain' WHERE reply_state='sending'")

    def start(self):
        if self.settings.channel_worker_enabled:
            self.thread = threading.Thread(target=self.loop, daemon=True, name="relay-channels")
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()  # Finish active job before closing graph/database resources.
        self.http.close()

    def status(self):
        s = self.settings
        return {
            "voice": self.voice.status(),
            "worker_enabled": s.channel_worker_enabled,
            "whatsapp": {
                "enabled": s.whatsapp_enabled,
                "linked_users": len(self.links),
                "configured": bool(
                    s.whatsapp_app_secret and s.whatsapp_verify_token and s.whatsapp_phone_number_id
                ),
                "replies_enabled": s.whatsapp_send_enabled,
                "token_configured": bool(s.whatsapp_access_token),
            },
        }

    def enqueue(self, source, external_id, principal, payload, sender=""):
        with self.store.lock:
            existing = self.store.query("SELECT id FROM channel_jobs WHERE external_id=?", (external_id,))
            if existing:
                return existing[0]["id"]
            rate = self.store.query(
                "SELECT count(*) AS n FROM channel_jobs WHERE tenant=? AND actor=? AND created>?",
                (principal.tenant_id, principal.actor, time.time() - 60),
            )[0]["n"]
            if rate >= 10:
                raise ValueError("Channel rate limit: wait one minute")
            job = str(uuid4())
            self.store.query(
                "INSERT INTO channel_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job,
                    source,
                    external_id,
                    principal.tenant_id,
                    principal.actor,
                    principal.role,
                    sender,
                    json.dumps(payload),
                    "queued",
                    "{}",
                    time.time(),
                    "pending" if sender else "disabled",
                ),
            )
            return job

    def jobs(self, principal):
        rows = self.store.query(
            "SELECT id,source,state,result,created,reply_state FROM channel_jobs WHERE tenant=? AND actor=? ORDER BY created DESC LIMIT 30",
            (principal.tenant_id, principal.actor),
        )
        return [{**r, "result": json.loads(r["result"])} for r in rows]

    def webhook(self, raw, signature):
        s = self.settings
        if not s.whatsapp_enabled or not s.whatsapp_app_secret:
            raise ValueError("WhatsApp is not configured")
        expected = "sha256=" + hmac.new(s.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("Invalid webhook signature")
        body = json.loads(raw)
        if body.get("object") != "whatsapp_business_account":
            return
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if value.get("metadata", {}).get("phone_number_id") != s.whatsapp_phone_number_id:
                    continue
                for msg in value.get("messages", []):
                    sender = msg.get("from", "")
                    principal = self.links.get(sender)
                    if not principal:
                        continue
                    try:
                        timestamp = float(msg["timestamp"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    if not time.time() - 3600 < timestamp < time.time() + 300:
                        continue
                    message_id = msg.get("id", "")
                    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 256:
                        continue
                    kind = msg.get("type")
                    if kind == "text":
                        text = msg.get("text", {}).get("body", "")
                        if not isinstance(text, str) or not 1 <= len(text) <= 2000:
                            continue
                        payload = {"text": text, "voice": False}
                    elif kind == "audio":
                        media_id = msg.get("audio", {}).get("id", "")
                        if not re.fullmatch(r"[0-9]{1,100}", media_id):
                            continue
                        payload = {"media_id": media_id, "voice": True}
                    else:
                        continue
                    self.enqueue("whatsapp", "wa:" + message_id, principal, payload, sender)

    def download_audio(self, media_id):
        s = self.settings
        if not s.whatsapp_access_token:
            raise ValueError("WhatsApp media token is not configured")
        headers = {"Authorization": "Bearer " + s.whatsapp_access_token}
        r = self.http.get(
            f"https://graph.facebook.com/{s.whatsapp_graph_version}/{media_id}", headers=headers
        )
        r.raise_for_status()
        meta = r.json()
        if meta.get("file_size", 0) > 5_000_000 or not meta.get("mime_type", "").startswith("audio/"):
            raise ValueError("Only audio under 5 MB is supported")
        url = meta.get("url", "")
        parsed = urlparse(url)
        # Never send the Meta token to a webhook-provided host or follow redirects.
        if (
            parsed.scheme != "https"
            or parsed.hostname != "lookaside.fbsbx.com"
            or parsed.username
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Unrecognized Meta media host")
        data = bytearray()
        with self.http.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 5_000_000:
                    raise ValueError("Audio exceeds 5 MB")
        return bytes(data)

    def owned_run(self, run_id, principal):
        rows = self.store.query(
            "SELECT result FROM channel_jobs WHERE tenant=? AND actor=?",
            (principal.tenant_id, principal.actor),
        )
        if not any(json.loads(r["result"]).get("run_id") == run_id for r in rows):
            raise ValueError("Run is not linked to this WhatsApp identity")
        return self.agent.view(run_id, principal)

    def describe(self, run):
        after = run.get("plan", {}).get("after", {})
        result = {"run_id": run["id"], "status": run["status"]}
        message = f"DEV run {run['id']}: {run['status']}."
        if run.get("pending"):
            message += (
                f"\nAction: {after.get('action')}\nPackage: {after.get('package_id')}"
                f"\niFlow: {after.get('artifact_id')}\nRisk: {run.get('plan', {}).get('risk', '')}"
                f"\nReview the full diff in Relay Activity.\nAPPROVE {run['id']} {run['plan_hash']}"
                f"\nOr REJECT {run['id']} {run['plan_hash']}"
            )
        result["message"] = message
        return result

    def handle(self, payload, principal):
        if principal.role not in ("operator", "approver"):
            raise ValueError("A linked operator or approver is required")
        text = payload["text"].strip()
        control = re.fullmatch(r"(APPROVE|REJECT) ([a-f0-9-]{36}) ([a-f0-9]{64})", text)
        if control:
            if payload.get("voice") or principal.role != "approver":
                raise ValueError("Approval requires an explicit text command from a linked approver")
            self.owned_run(control[2], principal)
            return self.describe(
                self.agent.decide(
                    control[2], Decision(approve=control[1] == "APPROVE", plan_hash=control[3]), principal
                )
            )
        if text.startswith("STATUS "):
            return self.describe(self.owned_run(text[7:].strip(), principal))
        if text == "HELP":
            return {
                "message": "Use BUILD: description for a description-driven HTTPS JSON pipeline, /package ID Name, /deploy PACKAGE IFLOW, or /orders PACKAGE IFLOW /relay/path scenario. External adapters require their connection details. Voice notes create plans only. Approve by typing the exact command returned with your plan."
            }
        if text.lower().startswith("build:"):
            result = describe(
                DescriptionRequest(description=text[6:].strip()), principal, self.agent, self.planner
            )
            if not result["supported"]:
                return {"message": result["explanation"] + " " + " ".join(result["questions"])}
            return self.describe(result["run"])
        parts = text.split(maxsplit=4)
        if parts[0] == "/package" and len(parts) >= 2:
            request = RunRequest(
                action="create_package",
                package_id=parts[1],
                name=text.split(maxsplit=2)[2] if len(parts) > 2 else parts[1],
                goal=text,
            )
        elif parts[0] == "/deploy" and len(parts) == 3:
            request = RunRequest(action="deploy", package_id=parts[1], artifact_id=parts[2], goal=text)
        elif parts[0] == "/orders" and len(parts) == 5:
            proposed = propose_orders(
                ScenarioRequest(
                    package_id=parts[1], artifact_id=parts[2], endpoint_path=parts[3], scenario=parts[4]
                ),
                self.planner,
            )["draft"]
            if not proposed["supported"]:
                return {"message": proposed["explanation"] + " " + " ".join(proposed["questions"])}
            flow = compile_orders(OrderDesignSpec.model_validate(proposed["design"]))
            request = RunRequest(
                action="upload_deploy",
                package_id=parts[1],
                artifact_id=parts[2],
                artifact_content=flow["artifact_content"],
                goal=text,
            )
        else:
            proposal = self.planner.propose(text)
            if not proposal.get("supported"):
                return {
                    "message": proposal.get("explanation", "Please include explicit package and iFlow IDs")
                }
            request = RunRequest.model_validate(proposal["request"])
        return self.describe(self.agent.start(request, principal))

    def process_one(self):
        with self.store.lock:
            rows = self.store.query(
                "SELECT * FROM channel_jobs WHERE state='queued' ORDER BY created LIMIT 1"
            )
            if not rows:
                return False
            row = rows[0]
            self.store.query("UPDATE channel_jobs SET state='processing' WHERE id=?", (row["id"],))
        principal = Principal(tenant_id=row["tenant"], actor=row["actor"], role=row["role"])
        try:
            payload = json.loads(row["payload"])
            if row["source"] == "whatsapp":
                if self.links.get(row["sender"]) != principal:
                    raise ValueError("WhatsApp identity is no longer linked")
                if "media_id" in payload:
                    payload["text"] = self.voice.transcribe(self.download_audio(payload["media_id"]))["text"]
                result = self.handle(payload, principal)
            else:
                decision = BackgroundDecision.model_validate(payload)
                if principal.role != "approver":
                    raise ValueError("Approver role required")
                result = self.describe(
                    self.agent.decide(
                        decision.run_id,
                        Decision(approve=decision.approve, plan_hash=decision.plan_hash),
                        principal,
                    )
                )
            state = "done"
        except Exception:
            # Do not leak payloads, provider URLs/tokens or raw validation errors in replies/logs.
            result, state = (
                {
                    "message": "Request needs attention. Check Relay Activity and channel setup. No automatic retry; inspect any existing run before resubmitting."
                },
                "needs_attention",
            )
        self.store.query(
            "UPDATE channel_jobs SET state=?,result=?,payload=? WHERE id=?",
            (state, json.dumps(result), "{}", row["id"]),
        )
        return True

    def send_one(self):
        if not self.settings.whatsapp_send_enabled or not self.settings.whatsapp_access_token:
            return
        rows = self.store.query(
            "SELECT * FROM channel_jobs WHERE state IN ('done','needs_attention') AND reply_state='pending' ORDER BY created LIMIT 1"
        )
        if not rows:
            return
        row = rows[0]
        if time.time() - row["created"] >= 23 * 3600 or self.links.get(row["sender"]) != Principal(
            tenant_id=row["tenant"], actor=row["actor"], role=row["role"]
        ):
            self.store.query("UPDATE channel_jobs SET reply_state='expired' WHERE id=?", (row["id"],))
            return
        self.store.query("UPDATE channel_jobs SET reply_state='sending' WHERE id=?", (row["id"],))
        try:
            r = self.http.post(
                f"https://graph.facebook.com/{self.settings.whatsapp_graph_version}/{self.settings.whatsapp_phone_number_id}/messages",
                headers={"Authorization": "Bearer " + self.settings.whatsapp_access_token},
                json={
                    "messaging_product": "whatsapp",
                    "to": row["sender"],
                    "type": "text",
                    "text": {"body": json.loads(row["result"])["message"][:4000]},
                },
            )
            r.raise_for_status()
            state = "sent"
        except Exception:
            state = "uncertain"  # Provider may have accepted: never blindly replay a send.
        self.store.query("UPDATE channel_jobs SET reply_state=? WHERE id=?", (state, row["id"]))

    def loop(self):
        while not self.stop.is_set():
            try:
                self.process_one()
                self.send_one()
            except Exception:
                pass  # Persisted state remains inspectable; no sensitive exception logging.
            self.stop.wait(1)
