"""Bounded SAP OData adapter. No caller-controlled hosts or arbitrary tool URLs."""
import time
from urllib.parse import urljoin, urlparse

import httpx

from .config import credential
from .models import identifier


class SAPError(Exception):
    def __init__(self, message, status=502, *, upstream_status=None, phase="api"):
        super().__init__(message)
        self.status = status
        self.upstream_status = upstream_status
        self.phase = phase


def unwrap(response):
    if not response.content:
        return {}
    try:
        value = response.json()
        return value.get('d', value) if isinstance(value, dict) else value
    except ValueError:
        return response.text.strip().strip('"')


class SAPClient:
    def __init__(self, tenant, transport=None):
        self.tenant = tenant
        self.http = httpx.Client(timeout=30, follow_redirects=False, transport=transport)
        self.token = None
        self.expires = 0
        self.csrf = None

    def close(self):
        self.http.close()

    def request(self, method, path, **kwargs):
        try:
            return self._request(method, path, **kwargs)
        except httpx.HTTPError:
            raise SAPError('SAP connection failed or timed out; inspect the tenant before retrying writes') from None

    def _request(self, method, path, **kwargs):
        if not self.token or time.monotonic() >= self.expires:
            response = self.http.post(self.tenant.token_url,
                auth=(credential(self.tenant.client_id_env), credential(self.tenant.client_secret_env)),
                data={'grant_type': 'client_credentials'})
            if not response.is_success:
                raise SAPError(f'SAP OAuth failed (HTTP {response.status_code}); check client credentials and token URL', upstream_status=response.status_code, phase='oauth')
            value = response.json()
            self.token = value['access_token']
            self.expires = time.monotonic() + max(0, int(value.get('expires_in', 300)) - 30)
            self.csrf = None
        headers = {'Authorization': f'Bearer {self.token}', 'Accept': 'application/json'}
        if method != 'GET':
            if not self.csrf:
                response = self.http.get(self.tenant.api_url + '/', headers={**headers, 'X-CSRF-Token': 'Fetch'})
                if not response.is_success:
                    raise SAPError(f'SAP CSRF fetch failed (HTTP {response.status_code})', upstream_status=response.status_code, phase='csrf')
                self.csrf = response.headers.get('x-csrf-token')
                if not self.csrf:
                    raise SAPError('SAP did not return a CSRF token; check service permissions')
            headers['X-CSRF-Token'] = self.csrf
        response = self.http.request(method, self.tenant.api_url + '/' + path, headers=headers, **kwargs)
        if response.status_code == 404:
            raise SAPError('SAP artifact or API was not found; verify the API-plan management URL and requested resource', 404, upstream_status=404)
        if not response.is_success:
            # Do not expose response bodies: they may contain credentials, scripts or message payloads.
            raise SAPError(f'SAP request failed (HTTP {response.status_code}); inspect tenant diagnostics', upstream_status=response.status_code)
        return unwrap(response)

    def collection(self, path, params=None):
        values = []
        for _ in range(20):
            page = self.request('GET', path, params=params)
            if not isinstance(page, dict) or not isinstance(page.get('results'), list):
                raise SAPError('Unexpected OData collection response')
            values.extend(page.get('results', []))
            next_url = page.get('__next')
            if not next_url:
                return values
            absolute = urljoin(self.tenant.api_url + '/', next_url)
            prefix = self.tenant.api_url + '/'
            if not absolute.startswith(prefix) or urlparse(absolute).netloc != urlparse(prefix).netloc:
                raise SAPError('Cross-origin OData continuation was blocked')
            path, params = absolute[len(prefix):], None
        raise SAPError('OData pagination exceeded 20 pages; narrow the query')

    def partner_parameters(self):
        return self.collection('StringParameters', {'$top': '20', '$select': 'Pid,Id'})

    def partner_parameter(self, partner_id, parameter_id):
        return self.request('GET', f"StringParameters(Pid='{identifier(partner_id)}',Id='{identifier(parameter_id)}')")

    def create_partner_parameter(self, request):
        return self.request('POST', 'StringParameters', json={'Pid': request['partner_id'],
            'Id': request['parameter_id'], 'Value': request['parameter_value']})

    def packages(self):
        return self.collection('IntegrationPackages', {'$format': 'json'})

    def package(self, package_id):
        return self.request('GET', f"IntegrationPackages('{identifier(package_id)}')")

    def flows(self, package_id):
        return self.collection(f"IntegrationPackages('{identifier(package_id)}')/IntegrationDesigntimeArtifacts")

    def flow(self, artifact_id, version='active'):
        return self.request('GET', f"IntegrationDesigntimeArtifacts(Id='{identifier(artifact_id)}',Version='{identifier(version)}')")

    def create_package(self, request):
        return self.request('POST', 'IntegrationPackages', json={
            'Id': request['package_id'], 'Name': request['name'], 'ShortText': 'Created by SAP Integration Agent'})

    def upload(self, request):
        if not self.tenant.allow_upload:
            raise ValueError('Artifact upload is disabled for this tenant')
        return self.request('POST', 'IntegrationDesigntimeArtifacts', json={
            'Id': request['artifact_id'], 'Name': request['artifact_id'],
            'PackageId': request['package_id'], 'ArtifactContent': request['artifact_content']})

    def deploy(self, request):
        result = self.request('POST', 'DeployIntegrationDesigntimeArtifact', params={
            'Id': "'" + identifier(request['artifact_id']) + "'",
            'Version': "'" + identifier(request['version']) + "'"})
        task = result if isinstance(result, str) else result.get('TaskId')
        if not task and isinstance(result, dict):
            nested = result.get('DeployIntegrationDesigntimeArtifact')
            task = nested if isinstance(nested, str) else (nested or {}).get('TaskId')
        if not task:
            raise SAPError('Deployment returned no task ID; inspect SAP before retrying')
        return {'task_id': identifier(task)}

    def build(self, task_id):
        return self.request('GET', f"BuildAndDeployStatus(TaskId='{identifier(task_id)}')")

    def runtime(self, artifact_id):
        return self.request('GET', f"IntegrationRuntimeArtifacts('{identifier(artifact_id)}')")

    def mpl(self, artifact_id):
        rows = self.collection('MessageProcessingLogs', {'$filter': f"IntegrationFlowName eq '{identifier(artifact_id)}'",
            '$top': '20', '$orderby': 'LogStart desc', '$select': 'MessageGuid,Status,LogStart,LogEnd,IntegrationFlowName'})
        return rows


class DemoClient:
    def __init__(self, tenant, store):
        self.tenant, self.store = tenant, store
        if not store.demo_get(tenant.id, 'package', 'AgentSandbox'):
            store.demo_put(tenant.id, 'package', 'AgentSandbox', {'Id': 'AgentSandbox', 'Name': 'Agent Sandbox'})
            store.demo_put(tenant.id, 'flow', 'HelloWorld', {'Id': 'HelloWorld', 'Name': 'Hello World',
                'PackageId': 'AgentSandbox', 'Version': '1.0.0'})

    def close(self):
        pass

    def get(self, kind, item):
        value = self.store.demo_get(self.tenant.id, kind, item)
        if value is None:
            raise SAPError('Demo artifact not found', 404)
        return value

    def partner_parameters(self):
        return [{k: v for k, v in row.items() if k in ('Pid', 'Id')}
                for row in self.store.demo_get(self.tenant.id, 'partner')]

    def partner_parameter(self, partner_id, parameter_id):
        return self.get('partner', partner_id + ':' + parameter_id)

    def create_partner_parameter(self, request):
        key = request['partner_id'] + ':' + request['parameter_id']
        if self.store.demo_get(self.tenant.id, 'partner', key):
            raise ValueError('Partner parameter already exists')
        return self.store.demo_put(self.tenant.id, 'partner', key,
            {'Pid': request['partner_id'], 'Id': request['parameter_id'], 'Value': request['parameter_value']})

    def packages(self):
        return self.store.demo_get(self.tenant.id, 'package')

    def package(self, package_id):
        return self.get('package', package_id)

    def flows(self, package_id):
        return [v for v in self.store.demo_get(self.tenant.id, 'flow') if v['PackageId'] == package_id]

    def flow(self, artifact_id, version='active'):
        value = self.get('flow', artifact_id)
        if version != 'active' and version != value['Version']:
            raise SAPError('Demo version not found', 404)
        return value

    def create_package(self, request):
        if self.store.demo_get(self.tenant.id, 'package', request['package_id']):
            raise ValueError('Package already exists')
        return self.store.demo_put(self.tenant.id, 'package', request['package_id'],
            {'Id': request['package_id'], 'Name': request['name']})

    def upload(self, request):
        if self.store.demo_get(self.tenant.id, 'flow', request['artifact_id']):
            raise ValueError('Artifact already exists')
        return self.store.demo_put(self.tenant.id, 'flow', request['artifact_id'],
            {'Id': request['artifact_id'], 'Name': request['artifact_id'], 'PackageId': request['package_id'], 'Version': '1.0.0'})

    def deploy(self, request):
        self.flow(request['artifact_id'], request['version'])
        self.store.demo_put(self.tenant.id, 'runtime', request['artifact_id'],
                            {'Id': request['artifact_id'], 'Status': 'STARTED'})
        return {'task_id': 'demo-' + request['artifact_id']}

    def build(self, task_id):
        return {'TaskId': task_id, 'Status': 'Success'}

    def runtime(self, artifact_id):
        return self.get('runtime', artifact_id)

    def mpl(self, artifact_id):
        return []  # No synthetic message is presented as a real business transaction.
