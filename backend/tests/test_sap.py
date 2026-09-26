import json

import httpx
import pytest

from app.config import Tenant
from app.sap import SAPClient, SAPError


def make_client(monkeypatch, handler):
    monkeypatch.setenv('TEST_CLIENT', 'client')
    monkeypatch.setenv('TEST_SECRET', 'secret')
    tenant = Tenant(id='test', name='Test', mode='sap', api_url='https://tenant.example/api/v1',
                    token_url='https://oauth.example/oauth/token', client_id_env='TEST_CLIENT',
                    client_secret_env='TEST_SECRET', allow_upload=True)
    return SAPClient(tenant, transport=httpx.MockTransport(handler))


def test_oauth_csrf_cookies_and_deploy(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == 'oauth.example':
            assert b'client_credentials' in request.content
            return httpx.Response(200, json={'access_token':'oauth-token', 'expires_in':3600})
        assert request.headers['Authorization'] == 'Bearer oauth-token'
        if request.headers.get('X-CSRF-Token') == 'Fetch':
            return httpx.Response(200, headers={'X-CSRF-Token':'csrf', 'Set-Cookie':'session=abc; Path=/'})
        assert request.headers['X-CSRF-Token'] == 'csrf'
        assert 'session=abc' in request.headers['Cookie']
        assert request.url.params['Id'] == "'HelloWorld'"
        assert request.url.path.endswith('/DeployIntegrationDesigntimeArtifact')
        return httpx.Response(202, text='task-123')
    client = make_client(monkeypatch, handler)
    assert client.deploy({'artifact_id':'HelloWorld', 'version':'active'}) == {'task_id':'task-123'}
    assert len(calls) == 3
    client.close()


def test_paginated_collection_and_host_guard(monkeypatch):
    pages = 0
    def handler(request):
        nonlocal pages
        if request.url.host == 'oauth.example':
            return httpx.Response(200, json={'access_token':'token'})
        pages += 1
        if pages == 1:
            return httpx.Response(200, json={'d':{'results':[{'Id':'One'}], '__next':'https://tenant.example/api/v1/IntegrationPackages?$skiptoken=2'}})
        return httpx.Response(200, json={'d':{'results':[{'Id':'Two'}]}})
    client = make_client(monkeypatch, handler)
    assert [x['Id'] for x in client.packages()] == ['One', 'Two']
    client.close()
    def malicious(request):
        if request.url.host == 'oauth.example':
            return httpx.Response(200, json={'access_token':'token'})
        return httpx.Response(200, json={'d':{'results':[], '__next':'https://evil.example/steal'}})
    client = make_client(monkeypatch, malicious)
    with pytest.raises(SAPError, match='Cross-origin'):
        client.packages()
    client.close()


def test_upload_contract(monkeypatch):
    def handler(request):
        if request.url.host == 'oauth.example':
            return httpx.Response(200, json={'access_token':'token'})
        if request.headers.get('X-CSRF-Token') == 'Fetch':
            return httpx.Response(200, headers={'X-CSRF-Token':'csrf'})
        assert request.url.path == '/api/v1/IntegrationDesigntimeArtifacts'
        assert json.loads(request.content) == {'Id':'Flow','Name':'Flow','PackageId':'Package','ArtifactContent':'UEs='}
        return httpx.Response(201, json={'d':{'Id':'Flow'}})
    client = make_client(monkeypatch, handler)
    assert client.upload({'artifact_id':'Flow','package_id':'Package','artifact_content':'UEs='})['Id'] == 'Flow'
    client.close()
