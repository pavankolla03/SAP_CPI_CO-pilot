"""Read-only capability adapters. Missing service credentials are not simulated success."""
import httpx

from .config import credential
from .sap import SAPError
from .diagnostics import remediation


class ServiceReader:
    def __init__(self, connection, transport=None):
        self.connection = connection
        self.transport = transport

    def read(self, path):
        config = self.connection
        with httpx.Client(timeout=30, follow_redirects=False, transport=self.transport) as client:
            if config.api_token_env:
                token = credential(config.api_token_env)
            else:
                r = client.post(config.token_url, auth=(credential(config.client_id_env), credential(config.client_secret_env)),
                                data={'grant_type': 'client_credentials'})
                if r.status_code != 200:
                    raise SAPError(f'Service OAuth failed (HTTP {r.status_code})')
                token = r.json()['access_token']
            r = client.get(config.api_url.rstrip('/') + path, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
            if not r.is_success:
                raise SAPError(f'Service inventory failed (HTTP {r.status_code})')
            try:
                return r.json()
            except ValueError:
                raise SAPError('Service returned an unexpected response format') from None


def service_inventory(tenant, capability):
    config = getattr(tenant, capability)
    if not config:
        raise ValueError(f'{capability.upper()} is not configured; a separate service URL and credential are required')
    path = {'apim': '/apiportal/api/1.0/Management.svc/APIProxies?$format=json&$top=50',
            'aem': '/api/v2/missionControl/eventBrokerServices?pageSize=50'}[capability]
    return ServiceReader(config).read(path)


def probe(tenant, client):
    results = []
    def check(name, fn):
        try:
            data = fn()
            results.append({'capability': name, 'status': 'accessible',
                            'detail': 'Read API returned successfully; write permissions not inferred',
                            'sample_count': len(data) if isinstance(data, list) else None})
        except SAPError as error:
            results.append({'capability': name, 'status': 'blocked',
                'detail': str(error) + '. ' + remediation(error),
                'upstream_status': error.upstream_status, 'phase': error.phase})
        except (ValueError, httpx.HTTPError):
            results.append({'capability': name, 'status': 'blocked',
                'detail': 'API unavailable, wrong service URL, or missing permission. Check the matching service key.'})
    check('cloud_integration', client.packages)
    check('b2b_partner_directory', lambda: client.partner_parameters())
    for name in ('apim', 'aem'):
        if getattr(tenant, name) is None:
            results.append({'capability': name, 'status': 'not_configured',
                            'detail': 'Separate service URL and credential required'})
        else:
            check(name, lambda n=name: service_inventory(tenant, n))
    results.append({'capability': 'b2b_tpm', 'status': 'not_implemented',
                    'detail': 'Partner Directory is not full TPM/agreements or AS2 business testing'})
    return {'mode': tenant.mode, 'environment': tenant.environment, 'results': results}
