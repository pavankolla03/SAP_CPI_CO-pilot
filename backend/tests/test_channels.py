import hashlib
import hmac
import json
import time

import httpx
import pytest

from app.config import Principal
from app.channels import Channels
from app.models import RunRequest
from test_agent import TOKEN, OTHER, OPERATOR

PHONE = "15555550123"


def configure(client):
    ch = client.app.state.channels
    ch.settings.whatsapp_enabled = True
    ch.settings.whatsapp_app_secret = "synthetic-app-secret"
    ch.settings.whatsapp_verify_token = "synthetic-verify-token"
    ch.settings.whatsapp_phone_number_id = "123456"
    ch.links[PHONE] = Principal(tenant_id="a", actor="alice", role="approver")
    return ch


def webhook(
    client,
    text="/package VoiceDemo Voice Demo",
    mid="wamid.test1",
    sender=PHONE,
    audio=None,
    signature=True,
    age=0,
):
    msg = {
        "id": mid,
        "from": sender,
        "timestamp": str(int(time.time() - age)),
        "type": "text",
        "text": {"body": text},
    }
    if audio:
        msg.update(type="audio", audio={"id": audio})
    body = {
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "123456"}, "messages": [msg]}}]}],
    }
    raw = json.dumps(body).encode()
    sig = (
        "sha256=" + hmac.new(b"synthetic-app-secret", raw, hashlib.sha256).hexdigest() if signature else "bad"
    )
    return client.post("/webhooks/whatsapp", content=raw, headers={"x-hub-signature-256": sig})


def test_webhook_verification_and_signature(client):
    configure(client)
    path = "/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=hello&hub.verify_token="
    assert client.get(path + "wrong").status_code == 403
    assert client.get(path + "synthetic-verify-token").text == "hello"
    assert webhook(client, signature=False).status_code == 401
    assert client.get("/v1/channel-jobs").json() == []


def test_signed_webhook_plan_approve_duplicate_and_tenant_isolation(client):
    ch = configure(client)
    assert webhook(client).status_code == 200
    assert webhook(client).status_code == 200
    assert len(client.get("/v1/channel-jobs").json()) == 1
    assert client.get("/v1/packages/VoiceDemo").status_code == 404
    ch.process_one()
    job = client.get("/v1/channel-jobs").json()[0]
    assert job["state"] == "done"
    run = client.get("/v1/runs/" + job["result"]["run_id"]).json()
    assert run["status"] == "awaiting_approval"
    assert client.get("/v1/packages/VoiceDemo").status_code == 404
    command = f"APPROVE {run['id']} {run['plan_hash']}"
    assert webhook(client, command, mid="wamid.approve").status_code == 200
    ch.process_one()
    assert client.get("/v1/packages/VoiceDemo").status_code == 200
    assert webhook(client, command, mid="wamid.approve").status_code == 200
    assert not ch.process_one()
    client.headers["Authorization"] = "Bearer " + OTHER
    assert client.get("/v1/channel-jobs").json() == []
    assert client.get("/v1/runs/" + run["id"]).status_code == 404
    client.headers["Authorization"] = "Bearer " + TOKEN
    assert "text" not in ch.store.query("SELECT payload FROM channel_jobs")[0]["payload"]


def test_unknown_sender_stale_wrong_phone_are_ignored(client):
    ch = configure(client)
    assert webhook(client, sender="15555550999").status_code == 200
    assert webhook(client, age=90000).status_code == 200
    ch.settings.whatsapp_phone_number_id = "999"
    assert webhook(client).status_code == 200
    assert client.get("/v1/channel-jobs").json() == []


def test_voice_cannot_approve_even_exact_transcription(client, monkeypatch):
    ch = configure(client)
    p = ch.links[PHONE]
    run = client.app.state.agent.start(RunRequest(action="create_package", package_id="VoiceBlocked"), p)
    monkeypatch.setattr(ch, "download_audio", lambda _: b"audio")
    monkeypatch.setattr(ch.voice, "transcribe", lambda _: {"text": f"APPROVE {run['id']} {run['plan_hash']}"})
    webhook(client, audio="12345")
    ch.process_one()
    assert client.get("/v1/channel-jobs").json()[0]["state"] == "needs_attention"
    assert client.get("/v1/packages/VoiceBlocked").status_code == 404


def test_audio_note_creates_plan_not_execution(client, monkeypatch):
    ch = configure(client)
    monkeypatch.setattr(ch, "download_audio", lambda _: b"audio")
    monkeypatch.setattr(ch.voice, "transcribe", lambda _: {"text": "/package AudioNote Audio Note"})
    webhook(client, audio="12345")
    ch.process_one()
    job = client.get("/v1/channel-jobs").json()[0]
    assert job["result"]["status"] == "awaiting_approval"
    assert client.get("/v1/packages/AudioNote").status_code == 404


def test_background_approval_and_role_gate(client):
    ch = client.app.state.channels
    ch.settings.channel_worker_enabled = True
    run = client.post("/v1/runs", json={"action": "create_package", "package_id": "BackgroundDemo"}).json()
    payload = {"run_id": run["id"], "approve": True, "plan_hash": run["plan_hash"]}
    client.headers["Authorization"] = "Bearer " + OPERATOR
    assert client.post("/v1/channel-jobs/decision", json=payload).status_code == 403
    client.headers["Authorization"] = "Bearer " + TOKEN
    first = client.post("/v1/channel-jobs/decision", json=payload)
    assert first.status_code == 202
    assert client.post("/v1/channel-jobs/decision", json=payload).json()["job_id"] == first.json()["job_id"]
    ch.process_one()
    assert client.get("/v1/packages/BackgroundDemo").status_code == 200
    assert client.get("/v1/channel-jobs").json()[0]["result"]["status"] == "succeeded"


def test_invalid_hash_and_foreign_channel_run(client):
    ch = configure(client)
    run = client.post("/v1/runs", json={"action": "create_package", "package_id": "NoChannelOwner"}).json()
    webhook(client, f"APPROVE {run['id']} {run['plan_hash']}")
    ch.process_one()
    assert client.get("/v1/packages/NoChannelOwner").status_code == 404
    assert client.get("/v1/channel-jobs").json()[0]["state"] == "needs_attention"


def test_interrupted_job_is_not_replayed(client):
    ch = configure(client)
    webhook(client)
    ch.store.query("UPDATE channel_jobs SET state='processing'")
    replacement = Channels(ch.settings, ch.agent, ch.planner, ch.voice)
    try:
        assert not replacement.process_one()
        assert replacement.jobs(ch.links[PHONE])[0]["state"] == "needs_attention"
    finally:
        replacement.close()


def test_media_download_checks_host_and_size(client):
    ch = configure(client)
    ch.settings.whatsapp_access_token = "fake-meta-token"
    requests = []

    def transport(request):
        requests.append(str(request.url))
        return httpx.Response(
            200, json={"url": "https://attacker.invalid/audio", "mime_type": "audio/ogg", "file_size": 10}
        )

    ch.http.close()
    ch.http = httpx.Client(transport=httpx.MockTransport(transport))
    with pytest.raises(ValueError, match="Unrecognized"):
        ch.download_audio("123")
    assert len(requests) == 1


def test_outbound_disabled_and_ambiguous_send_not_replayed(client):
    ch = configure(client)
    webhook(client, "HELP")
    ch.process_one()
    calls = []

    def transport(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic failure")

    ch.http.close()
    ch.http = httpx.Client(transport=httpx.MockTransport(transport))
    ch.settings.whatsapp_access_token = "fake-token"
    ch.send_one()
    assert not calls
    ch.settings.whatsapp_send_enabled = True
    ch.send_one()
    ch.send_one()
    assert len(calls) == 1
    assert ch.jobs(ch.links[PHONE])[0]["reply_state"] == "uncertain"


def test_voice_endpoint_auth_type_size_and_disabled(client):
    client.headers["Authorization"] = ""
    assert (
        client.post(
            "/v1/voice/transcribe", content=b"audio", headers={"content-type": "audio/ogg"}
        ).status_code
        == 401
    )
    client.headers["Authorization"] = "Bearer " + TOKEN
    assert (
        client.post(
            "/v1/voice/transcribe", content=b"audio", headers={"content-type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/v1/voice/transcribe", content=b"audio", headers={"content-type": "audio/ogg"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/voice/transcribe", content=b"x" * 5_500_001, headers={"content-type": "audio/ogg"}
        ).status_code
        == 413
    )


def test_description_builds_unique_plan_and_unsupported_does_not_write(client, monkeypatch):
    import app.scenarios as scenarios

    def proposal(target, planner):
        return {
            "draft": {
                "supported": True,
                "explanation": "Batch orders only",
                "questions": [],
                "design": {
                    "package_id": target.package_id,
                    "artifact_id": target.artifact_id,
                    "endpoint_path": target.endpoint_path,
                },
            },
            "model": "test-free-model",
        }

    monkeypatch.setattr(scenarios, "propose_orders", proposal)
    result = client.post(
        "/v1/scenarios/orders",
        json={"description": "Split and route incoming orders", "package_id": "AgentSandbox"},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["run"]["status"] == "awaiting_approval"
    assert body["design"]["artifact_id"].startswith("RelayOrders")
    assert client.get("/v1/iflows/" + body["design"]["artifact_id"]).status_code == 404
    monkeypatch.setattr(
        scenarios,
        "propose_orders",
        lambda *args: {
            "draft": {
                "supported": False,
                "explanation": "ERP writes not supported",
                "questions": ["Choose a supported pattern"],
            }
        },
    )
    assert not client.post(
        "/v1/scenarios/orders",
        json={"description": "Write all orders into an external ERP", "package_id": "AgentSandbox"},
    ).json()["supported"]
    assert len(client.get("/v1/runs").json()) == 1


def test_description_requires_existing_tenant_default(client):
    assert (
        client.post(
            "/v1/scenarios/orders", json={"description": "Split and route incoming orders"}
        ).status_code
        == 409
    )


def test_auto_description_builds_general_pipeline_and_preserves_target(client, monkeypatch):
    import app.scenarios as scenarios

    def pipeline(target, planner):
        return {
            "draft": {
                "supported": True,
                "explanation": "Explicit fields mapped",
                "questions": [],
                "design": {
                    "title": "Normalize customer",
                    "package_id": target.package_id,
                    "artifact_id": target.artifact_id,
                    "endpoint_path": target.endpoint_path,
                    "required_fields": ["customer.name", "customer.email"],
                    "mappings": [
                        {"source": "customer.name", "target": "customerName", "transform": "uppercase"},
                        {"source": "customer.email", "target": "email", "transform": "lowercase"},
                    ],
                },
            },
            "model": "test/free:free",
            "key_slot": 2,
        }

    monkeypatch.setattr(scenarios, "propose_pipeline", pipeline)
    response = client.post(
        "/v1/scenarios/compile",
        json={
            "description": "Require customer name and email, uppercase name and lowercase email",
            "package_id": "AgentSandbox",
            "pattern": "auto",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pattern"] == "json_pipeline"
    assert body["design"]["package_id"] == "AgentSandbox"
    assert body["design"]["artifact_id"].startswith("RelayFlow")
    assert body["key_slots"] == [2]
    assert body["run"]["status"] == "awaiting_approval"
    assert client.get("/v1/iflows/" + body["design"]["artifact_id"]).status_code == 404
    assert (
        client.post(
            "/v1/scenarios/orders",
            json={"description": "Split and route incoming orders", "package_id": "Missing"},
        ).status_code
        == 404
    )


def test_description_corrects_sample_mismatch_once_before_creating_plan(client, monkeypatch):
    import app.scenarios as scenarios
    calls = []
    def propose(target, planner):
        calls.append(target)
        return {'draft':{'supported':True,'questions':[],'explanation':'Normalize name','design':{
            'title':'Name','package_id':target.package_id,'artifact_id':target.artifact_id,'endpoint_path':target.endpoint_path,
            'required_fields':['name'],'mappings':[{'source':'name','target':'name','transform':'copy' if target.revision_feedback is None else 'uppercase'}]
        }},'key_slot':len(calls)}
    monkeypatch.setattr(scenarios,'propose_pipeline',propose)
    response=client.post('/v1/scenarios/compile',json={'description':'Uppercase the incoming name','package_id':'AgentSandbox','sample_input':{'name':'Ada'},'expected_output':{'name':'ADA'}})
    assert response.status_code==200
    assert len(calls)==2 and calls[1].revision_feedback['actual_output']=={'name':'Ada'}
    assert response.json()['sample_output']=={'name':'ADA'}
    assert response.json()['key_slots']==[1,2]
    assert response.json()['run']['status']=='awaiting_approval'
    assert client.get('/v1/iflows/'+response.json()['design']['artifact_id']).status_code==404
    before=client.get('/v1/runs').json()
    calls.clear()
    bad=client.post('/v1/scenarios/compile',json={'description':'Uppercase the incoming name','package_id':'AgentSandbox','sample_input':{'name':'Ada'},'expected_output':{'name':'WRONG'}})
    assert bad.status_code==409 and len(calls)==2
    assert client.get('/v1/runs').json()==before


def test_rate_limit_and_revoked_identity(client):
    ch = configure(client)
    for i in range(10):
        assert webhook(client, "HELP", mid=f"limit-{i}").status_code == 200
    assert webhook(client, "HELP", mid="over-limit").status_code == 400
    ch.links.clear()
    ch.process_one()
    assert (
        ch.store.query("SELECT state FROM channel_jobs ORDER BY created LIMIT 1")[0]["state"]
        == "needs_attention"
    )
