"""Bounded, read-only checks against configured tenant APIs; never guess hosts."""
from .sap import SAPError
from .models import identifier

# Request one row per check. Design APIs do not support every OData projection.
CHECKS = (
    ('packages', 'IntegrationPackages', 'Id'),
    ('design_artifacts', 'IntegrationDesigntimeArtifacts', 'Id'),
    ('runtime_artifacts', 'IntegrationRuntimeArtifacts', 'Id'),
    ('message_logs', 'MessageProcessingLogs', 'MessageGuid'),
    ('partner_directory', 'StringParameters', 'Pid,Id'),
)


def remediation(error):
    code = error.upstream_status
    if error.phase == 'oauth':
        return 'Verify the client ID, secret, token URL and client_credentials grant in the matching service key.'
    if code == 404:
        return 'Confirm the Process Integration Runtime api-plan management URL. A 404 is not an empty inventory; do not derive a hostname from the runtime URL.'
    if code in (401, 403):
        return 'Check API-client roles for this operation and that the token belongs to this tenant; authentication alone does not grant access.'
    if code == 429:
        return 'The service rate-limited this request. Wait before checking again.'
    if code and 300 <= code < 400:
        return 'The API redirected. Use the service-key API endpoint, not an interactive cockpit/login URL.'
    return 'Check network reachability and the documented OData endpoint. No write was attempted.'


def preflight(tenant, client):
    if tenant.mode != 'sap':
        return {'mode': tenant.mode, 'environment': tenant.environment, 'checks': [],
                'read_ready': False, 'write_access': 'unverified',
                'detail': 'Demo mode cannot verify SAP tenant access.'}
    rows = []
    oauth_failed = False
    package_id = None
    for name, path, fields in CHECKS:
        if oauth_failed:
            rows.append({'name': name, 'path': path, 'status': 'skipped',
                         'detail': 'Skipped after OAuth failure; correct credentials before retrying.'})
            continue
        try:
            if name == 'design_artifacts':
                if package_id is None:
                    rows.append({'name': name, 'path': path, 'status': 'skipped',
                                 'detail': 'No readable package available to probe package-scoped iFlows.'})
                    continue
                path = f"IntegrationPackages('{identifier(package_id)}')/IntegrationDesigntimeArtifacts"
            params = {'$top': '1', '$format': 'json'}
            if name not in ('packages', 'design_artifacts'):
                params['$select'] = fields
            page = client.request('GET', path, params=params)
            if not isinstance(page, dict) or not isinstance(page.get('results'), list):
                raise SAPError('Expected an OData results array; the endpoint returned a different format')
            if name == 'packages' and page['results']:
                package_id = page['results'][0].get('Id')
            rows.append({'name': name, 'path': path, 'status': 'accessible',
                         'detail': 'Read succeeded; write access remains unverified.'})
        except SAPError as error:
            rows.append({'name': name, 'path': path, 'status': 'blocked', 'phase': error.phase,
                         'upstream_status': error.upstream_status, 'detail': str(error),
                         'next_step': remediation(error)})
            oauth_failed = error.phase == 'oauth'
        except ValueError:
            rows.append({'name': name, 'path': path, 'status': 'blocked', 'phase': 'configuration',
                         'detail': 'Missing credentials or malformed authentication response.'})
            oauth_failed = True
    return {'mode': tenant.mode, 'environment': tenant.environment, 'checks': rows,
            'read_ready': all(row['status'] == 'accessible' for row in rows),
            'write_access': 'unverified', 'detail': 'Read-only probes; sampled records and message payloads are not returned.'}
