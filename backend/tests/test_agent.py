import base64
import io
import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TOKEN = 'test-approver-token-abcdefghijklmnopqrstuvwxyz'
OTHER = 'other-tenant-token-abcdefghijklmnopqrstuvwxyz'
VIEWER = 'viewer-token-abcdefghijklmnopqrstuvwxyz'
OPERATOR = 'operator-token-abcdefghijklmnopqrstuvwxyz'


@pytest.fixture
def settings(tmp_path):
    tenants = tmp_path / 'tenants.json'
    tenants.write_text(json.dumps([{'id': 'a', 'name': 'A'}, {'id': 'b', 'name': 'B'}]))
    return Settings(_env_file=None, data_dir=str(tmp_path / 'data'), tenants_file=str(tenants),
        api_keys_json=json.dumps({TOKEN: {'tenant_id': 'a', 'actor': 'alice', 'role': 'approver'},
                                 OTHER: {'tenant_id': 'b', 'actor': 'bob', 'role': 'approver'},
                                 VIEWER: {'tenant_id': 'a', 'actor': 'vic', 'role': 'viewer'},
                                 OPERATOR: {'tenant_id': 'a', 'actor': 'oliver', 'role': 'operator'}}),
        poll_seconds=0, poll_attempts=2, channel_worker_enabled=False, voice_enabled=False, whatsapp_enabled=False)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        yield c


def plan(client, **kwargs):
    response = client.post('/v1/runs', json=kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def decide(client, run, approve=True):
    return client.post(f"/v1/runs/{run['id']}/decision", json={'approve': approve, 'plan_hash': run['plan_hash']})


def test_deploy_approval_execution_and_test(client):
    run = plan(client)
    assert run['status'] == 'awaiting_approval'
    assert client.get('/v1/iflows/HelloWorld/runtime').status_code == 404
    result = decide(client, run)
    assert result.status_code == 200, result.text
    result = result.json()
    assert result['status'] == 'succeeded'
    assert result['test']['passed']
    compile(result['test']['code'], 'generated_test', 'exec')
    assert [e['phase'] for e in result['events']][-3:] == ['test', 'verify', 'audit']
    assert decide(client, run).status_code == 409


def test_rejection_has_no_writes(client):
    run = plan(client, action='create_package', package_id='Rejected')
    assert decide(client, run, False).json()['status'] == 'rejected'
    assert client.get('/v1/packages/Rejected').status_code == 404


def test_roles_hash_and_tenant_isolation(client):
    run = plan(client)
    assert client.post(f"/v1/runs/{run['id']}/decision", json={'approve': True, 'plan_hash': '0'*64}).status_code == 409
    client.headers['Authorization'] = 'Bearer ' + OTHER
    assert client.get(f"/v1/runs/{run['id']}").status_code == 404
    assert decide(client, run).status_code == 404
    assert client.get('/v1/runs').json() == []
    client.headers['Authorization'] = 'Bearer ' + VIEWER
    assert client.post('/v1/runs', json={}).status_code == 403
    assert decide(client, run).status_code == 403
    client.headers['Authorization'] = 'Bearer ' + OPERATOR
    assert decide(client, run).status_code == 403
    client.headers.clear()
    assert client.get('/v1/packages').status_code == 401


def test_restart_pending_approval(settings):
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        run = plan(client)
    with TestClient(create_app(settings)) as client:
        client.headers['Authorization'] = 'Bearer ' + TOKEN
        loaded = client.get(f"/v1/runs/{run['id']}").json()
        assert loaded['status'] == 'awaiting_approval'
        assert decide(client, loaded).json()['status'] == 'succeeded'


def test_stale_snapshot_blocks_write(client):
    run = plan(client)
    store = client.app.state.agent.store
    store.demo_put('a', 'flow', 'HelloWorld', {'Id': 'HelloWorld', 'PackageId': 'AgentSandbox', 'Version': '2.0'})
    result = decide(client, run).json()
    assert result['status'] == 'needs_attention'
    assert 'changed after planning' in result['error']
    assert client.get('/v1/iflows/HelloWorld/runtime').status_code == 404


def test_ambiguous_write_cannot_replay(client):
    run = plan(client)
    client.app.state.agent.store.query('INSERT INTO operations VALUES(?,?,?)', (run['id'] + ':deploy','started','{}'))
    result = decide(client, run).json()
    assert result['status'] == 'needs_attention'
    assert 'replay blocked' in result['error']
    assert client.get('/v1/iflows/HelloWorld/runtime').status_code == 404


def test_create_package_and_tenant_separation(client):
    run = plan(client, action='create_package', package_id='NewPackage', name='New Package')
    assert decide(client, run).json()['status'] == 'succeeded'
    assert client.get('/v1/packages/NewPackage').status_code == 200
    client.headers['Authorization'] = 'Bearer ' + OTHER
    assert client.get('/v1/packages/NewPackage').status_code == 404


def bundle(files=None):
    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, content in (files or {'META-INF/MANIFEST.MF':'Manifest-Version: 1.0',
                'src/main/resources/scenarioflows/integrationflow/Test.iflw':'<definitions />'}).items():
            archive.writestr(name, content)
    return base64.b64encode(output.getvalue()).decode()


def test_upload_and_deploy(client):
    run = plan(client, action='upload_deploy', artifact_id='NewFlow', artifact_content=bundle())
    assert 'artifact_content' not in json.dumps(run)
    assert run['plan']['bundle']['sha256']
    assert decide(client, run).json()['status'] == 'succeeded'


@pytest.mark.parametrize('content', ['not-base64', bundle({'../oops':'bad'}), bundle({'META-INF/MANIFEST.MF':'a','x.iflw':'<broken'})])
def test_invalid_zip_rejected(client, content):
    assert client.post('/v1/runs', json={'action':'upload_deploy', 'artifact_content':content}).status_code == 422


def test_identifier_injection_rejected(client):
    assert client.post('/v1/runs', json={'artifact_id': "x')/$value"}).status_code == 422


def test_failed_build_bounded_repair(client):
    sap = client.app.state.agent.clients['a']
    count = 0
    def build(task_id):
        nonlocal count
        count += 1
        return {'Status': 'Failed' if count == 1 else 'Success'}
    sap.build = build
    run = plan(client)
    repair = decide(client, run).json()
    assert repair['status'] == 'awaiting_repair'
    result = decide(client, repair).json()
    assert result['status'] == 'succeeded'
    assert result['attempt'] == 1
    assert 'redeploy' in [e['phase'] for e in result['events']]


def test_nonterminal_build_never_redeploys(client):
    client.app.state.agent.clients['a'].build = lambda task_id: {'Status':'Processing'}
    run = plan(client)
    result = decide(client, run).json()
    assert result['status'] == 'needs_attention'
    assert not result['pending']
    assert 'redeploy' not in [e['phase'] for e in result['events']]


def test_browser_preview_assets(client):
    response = client.get('/')
    assert response.url.path == '/ui/'
    assert client.get('/ui/panel.css').status_code == 200
    assert 'javascript' in client.get('/ui/panel.js').headers['content-type']


def test_completed_resume_blocked(client):
    run = plan(client)
    decide(client, run)
    assert client.post(f"/v1/runs/{run['id']}/resume", json={}).status_code == 409


def test_missing_package_and_overwrite_blocked(client):
    assert plan(client, package_id='Missing')['status'] == 'needs_attention'
    assert plan(client, action='upload_deploy', artifact_content=bundle())['status'] == 'needs_attention'


def test_smoke_failure_routes_to_fix(client):
    sap = client.app.state.agent.clients['a']
    original = sap.runtime
    calls = 0
    def changing_runtime(artifact_id):
        nonlocal calls
        calls += 1
        if calls > 1:
            return {'Id': artifact_id, 'Status': 'ERROR'}
        return original(artifact_id)
    sap.runtime = changing_runtime
    result = decide(client, plan(client)).json()
    assert result['status'] == 'needs_attention'
    assert result['test']['passed'] is False
    assert [e['phase'] for e in result['events']][-2:] == ['fix', 'audit']


def test_bad_management_host_cannot_produce_creation_plan(client):
    from app.sap import SAPError
    def missing_collection():
        raise SAPError('Management API is unavailable',404)
    client.app.state.agent.clients['a'].packages=missing_collection
    run=plan(client,action='create_package',package_id='ShouldNotExist')
    assert run['status']=='needs_attention'
    assert run['pending']==[]
    assert 'plan' not in [e['phase'] for e in run['events']]


def test_concurrent_mutation_rejected(client):
    lock=client.app.state.agent.lock
    lock.acquire()
    try:
        assert client.post('/v1/runs',json={}).status_code==409
    finally:
        lock.release()


def test_uppercase_sap_success(client):
    agent = client.app.state.agent
    agent.clients['a'].build = lambda task: {'TaskId': task, 'Status': 'SUCCESS'}
    run = plan(client)
    assert decide(client, run).json()['status'] == 'succeeded'
