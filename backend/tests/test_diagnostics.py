import httpx
import pytest

from app.diagnostics import preflight
from app.sap import SAPError
from test_sap import make_client


@pytest.mark.parametrize('code', [401, 403, 404, 429, 302])
def test_preflight_preserves_errors_without_leaking_body(monkeypatch, code):
    def handle(request):
        if request.url.host == 'oauth.example':
            return httpx.Response(200, json={'access_token': 'private-token'})
        assert request.method == 'GET'
        assert request.url.params['$top'] == '1'
        return httpx.Response(code, text='private-payload', headers={'Location': 'https://other.example'})
    client = make_client(monkeypatch, handle)
    result = preflight(client.tenant, client)
    assert not result['read_ready']
    assert result['write_access'] == 'unverified'
    assert all(row['upstream_status'] == code for row in result['checks'] if row['status'] != 'skipped')
    assert 'private' not in str(result)
    assert all(row['next_step'] for row in result['checks'] if row['status'] != 'skipped')
    client.close()


def test_oauth_failure_stops_remaining_checks(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(401, text='client-secret')
    client = make_client(monkeypatch, handle)
    result = preflight(client.tenant, client)
    assert len(calls) == 1
    assert result['checks'][0]['phase'] == 'oauth'
    assert all(row['status'] == 'skipped' for row in result['checks'][1:])
    client.close()


def test_successful_empty_inventory_is_not_missing_api(monkeypatch):
    def handle(request):
        if request.url.host == 'oauth.example':
            return httpx.Response(200, json={'access_token': 'token'})
        return httpx.Response(200, json={'d': {'results': []}})
    client = make_client(monkeypatch, handle)
    assert preflight(client.tenant, client)['checks'][1]['status'] == 'skipped'
    assert client.packages() == []
    client.close()


def test_html_and_wrong_json_do_not_count_as_empty_inventory(monkeypatch):
    def handle(request):
        if request.url.host == 'oauth.example':
            return httpx.Response(200, json={'access_token': 'token'})
        return httpx.Response(200, json={'error': 'not an OData collection'})
    client = make_client(monkeypatch, handle)
    assert not preflight(client.tenant, client)['read_ready']
    with pytest.raises(SAPError, match='Unexpected OData'):
        client.packages()
    client.close()


def test_diagnostics_requires_auth_and_demo_is_not_live(client):
    response = client.get('/v1/diagnostics')
    assert response.status_code == 200
    assert response.json()['mode'] == 'demo'
    assert not response.json()['read_ready']
    client.headers.pop('Authorization')
    assert client.get('/v1/diagnostics').status_code == 401


def test_designtime_uses_package_navigation_without_select(monkeypatch):
    def handle(request):
        if request.url.host == 'oauth.example':
            return httpx.Response(200, json={'access_token': 'token'})
        if request.url.path.endswith('/IntegrationPackages'):
            assert '$select' not in request.url.params
            return httpx.Response(200, json={'d': {'results': [{'Id': 'Package'}]}})
        if 'IntegrationDesigntimeArtifacts' in request.url.path:
            assert request.url.path == "/api/v1/IntegrationPackages('Package')/IntegrationDesigntimeArtifacts"
            assert '$select' not in request.url.params
        return httpx.Response(200, json={'d': {'results': []}})
    client = make_client(monkeypatch, handle)
    assert preflight(client.tenant, client)['read_ready']
    client.close()
