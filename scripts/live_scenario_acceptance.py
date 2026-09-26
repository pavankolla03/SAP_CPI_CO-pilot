"""Authorized bounded DEV acceptance for description-driven iFlows."""
import json
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.config import Settings, credential


def main():
    load_dotenv('.env')
    settings = Settings()
    token = next(
        token for token, principal in settings.principals().items()
        if principal.tenant_id == 'sap-dev' and principal.role == 'approver'
    )
    api = httpx.Client(
        base_url='http://127.0.0.1:8000',
        headers={'Authorization': 'Bearer ' + token},
        timeout=180,
    )
    package_id = 'RelayTest'
    package = api.get('/v1/packages/' + package_id)
    if package.status_code == 404:
        run = api.post('/v1/runs', json={
            'action': 'create_package', 'package_id': package_id,
            'name': 'relay test', 'goal': 'Create the Relay multi-scenario DEV acceptance package',
        })
        run.raise_for_status()
        planned = run.json()
        finished = api.post(
            f"/v1/runs/{planned['id']}/decision",
            json={'approve': True, 'plan_hash': planned['plan_hash']},
        )
        finished.raise_for_status()
        if finished.json()['status'] != 'succeeded':
            raise RuntimeError('RelayTest package creation failed')
    else:
        package.raise_for_status()

    cases = [
        {
            'name': 'order-routing',
            'pattern': 'batch_orders',
            'description': (
                'Receive an HTTPS JSON batch containing orders with id, amount and quantity. Reject duplicate IDs, '
                'split sequentially by ID, calculate amount times quantity, route totals above 1000 to REVIEW, valid '
                'lower totals to ACCEPTED, invalid values to REJECTED, gather results and handle exceptions.'
            ),
            'input': {'orders': [
                {'id': 'MULTI-1', 'amount': 20, 'quantity': 2},
                {'id': 'MULTI-2', 'amount': 600, 'quantity': 2},
                {'id': 'MULTI-3', 'amount': -1, 'quantity': 1},
            ]},
            'assert': lambda body: [row['status'] for row in body['orders']] == ['ACCEPTED', 'REVIEW', 'REJECTED'],
        },
        {
            'name': 'customer-normalization',
            'pattern': 'json_transform',
            'description': (
                'Receive one HTTPS JSON object. Require customer.name and customer.email. Map customer.name to '
                'customerName in uppercase and customer.email to email in lowercase. Return only those fields as JSON.'
            ),
            'input': {'customer': {'name': 'Ada Lovelace', 'email': 'ADA@EXAMPLE.COM'}},
            'assert': lambda body: body == {'customerName': 'ADA LOVELACE', 'email': 'ada@example.com'},
        },
        {
            'name': 'payment-validation',
            'pattern': 'json_transform',
            'description': (
                'Receive one HTTPS JSON object. Require payment.id, payment.amount and currency. Map payment.id to '
                'paymentId by copying it, payment.amount to amount as a number, and currency to currencyCode in uppercase. '
                'Return the flat JSON result.'
            ),
            'input': {'payment': {'id': 'PAY-7', 'amount': '45.50'}, 'currency': 'usd'},
            'assert': lambda body: body == {'paymentId': 'PAY-7', 'amount': 45.50, 'currencyCode': 'USD'},
        },
    ]
    evidence = {'package_id': package_id, 'package_name': 'relay test', 'scenarios': []}
    for case in cases:
        response = api.post('/v1/scenarios/compile', json={
            'description': case['description'], 'package_id': package_id, 'pattern': case['pattern'],
        })
        response.raise_for_status()
        proposed = response.json()
        if not proposed['supported']:
            raise RuntimeError(case['name'] + ' unsupported: ' + proposed['explanation'])
        planned = proposed['run']
        approved = api.post(
            f"/v1/runs/{planned['id']}/decision",
            json={'approve': True, 'plan_hash': planned['plan_hash']},
        )
        approved.raise_for_status()
        run = approved.json()
        if run['status'] != 'succeeded':
            raise RuntimeError(case['name'] + ' deployment: ' + run.get('error', run['status']))
        case['design'] = proposed['design']
        case['run_id'] = run['id']
        case['model'] = proposed.get('model')
        case['key_slots'] = proposed.get('key_slots', [])

    tenant = settings.tenants()['sap-dev']
    oauth = httpx.post(
        tenant.token_url,
        auth=(credential('SAP_RUNTIME_CLIENT_ID'), credential('SAP_RUNTIME_CLIENT_SECRET')),
        data={'grant_type': 'client_credentials'}, timeout=30,
    )
    oauth.raise_for_status()
    runtime_headers = {'Authorization': 'Bearer ' + oauth.json()['access_token']}
    runtime_base = tenant.api_url.removesuffix('/api/v1').replace('-cpitrial06.', '-cpitrial06-rt.')
    for case in cases:
        url = runtime_base + '/http' + case['design']['endpoint_path']
        response = httpx.post(url, headers=runtime_headers, json=case['input'], timeout=60)
        response.raise_for_status()
        body = response.json()
        if not case['assert'](body):
            raise RuntimeError(case['name'] + ' unexpected response: ' + json.dumps(body))
        evidence['scenarios'].append({
            'name': case['name'], 'pattern': case['pattern'], 'artifact_id': case['design']['artifact_id'],
            'endpoint_path': case['design']['endpoint_path'], 'run_id': case['run_id'],
            'model': case['model'], 'key_slots': case['key_slots'], 'http_status': response.status_code,
            'input': case['input'], 'output': body,
        })
        print(case['name'], case['design']['artifact_id'], response.status_code, json.dumps(body), flush=True)
    inventory = api.get(f'/v1/packages/{package_id}/iflows')
    inventory.raise_for_status()
    evidence['package_iflows'] = [row['Id'] for row in inventory.json()]
    Path('data/multi-scenario-acceptance.json').write_text(json.dumps(evidence, indent=2) + '\n')
    Path('docs/multi-scenario-acceptance.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS', len(evidence['scenarios']), 'scenarios; package contains', len(evidence['package_iflows']), 'iFlows')


if __name__ == '__main__':
    main()
