"""Explicit DEV acceptance: two independent outputs and two architecture guards.

Writes only new unique artifacts in RelayTest. Never overwrites or deletes flows.
Credentials remain in the existing local configuration.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
import httpx
from dotenv import load_dotenv
from app.config import Settings, credential


def main():
    load_dotenv('.env')
    settings = Settings()
    token = next(k for k, p in settings.principals().items() if p.tenant_id == 'sap-dev' and p.role == 'approver')
    evidence = {'at': datetime.now(timezone.utc).isoformat(), 'package': 'RelayTest', 'cases': []}
    path = Path('docs/solution-workspace-acceptance.json')
    def save():
        path.write_text(json.dumps(evidence, indent=2) + '\n')
    cases = [
        {'name': 'shipment-routing', 'description': 'Receive HTTPS JSON with shipments array. Require id and weight. Map id to shipmentId. Calculate billableWeight as weight multiplied by 1.2. Route billableWeight greater than 24 to FREIGHT, otherwise PARCEL. Return only shipmentId, billableWeight and status in shipments, with a count.',
         'sample_input': {'shipments': [{'id': 'S1', 'weight': 10}, {'id': 'S2', 'weight': 30}]},
         'expected_output': {'count': 2, 'shipments': [{'shipmentId': 'S1', 'billableWeight': 12, 'status': 'PARCEL'}, {'shipmentId': 'S2', 'billableWeight': 36, 'status': 'FREIGHT'}]}},
        {'name': 'customer-normalization', 'description': 'Receive one HTTPS JSON object. Require customer.id and customer.email. Map customer.id to customerId and customer.email to email in lowercase. Return only these two fields as a JSON object.',
         'sample_input': {'customer': {'id': 'C-42', 'email': 'HELLO@EXAMPLE.COM'}},
         'expected_output': {'customerId': 'C-42', 'email': 'hello@example.com'}},
        {'name': 'modular-sap-architecture', 'description': 'Create three connected iFlows: receive SOAP IDoc COSMAS01 from S4HANA, look up cost centers through OData, route payroll relevant cost centers via ProcessDirect to an ECP IDoc flow and send employee central costs to a separate SuccessFactors OData upsert flow. Preserve original XML and add exception subprocesses. Build a modular architecture; connection details will be provided later.', 'blocked': True},
        {'name': 'missing-business-rule', 'description': 'Receive HTTPS JSON orders with id and amount. Route high value orders to REVIEW and others to APPROVED. I have not decided the threshold. Ask me before choosing it.', 'blocked': True},
    ]
    with httpx.Client(base_url='http://127.0.0.1:8000', headers={'Authorization': 'Bearer '+token}, timeout=210) as api:
        for case in cases:
            row = {'name': case['name']}; evidence['cases'].append(row); save()
            try:
                body = {k:v for k,v in case.items() if k in ('description','sample_input','expected_output')}
                result = api.post('/v1/solutions/analyze', json={**body, 'package_id':'RelayTest'})
                assert result.status_code == 200, result.text
                plan = result.json()
                row.update(plan_id=plan['id'], status=plan['status'], buildable=plan['buildable'], questions=plan['questions'], blockers=plan['blockers'], model=plan['model'], key_slots=plan['key_slots'], flow_count=len(plan['flows']), references=plan['references'])
                save()
                if case.get('blocked'):
                    assert not plan['buildable'], 'Unsupported or incomplete plan incorrectly buildable'
                    assert api.post('/v1/solutions/'+plan['id']+'/build').status_code == 409
                    row['passed']=True;save();print(case['name'], 'correctly blocked', flush=True);continue
                assert plan['buildable'], json.dumps({'blockers':plan['blockers'],'questions':plan['questions']})
                build = api.post('/v1/solutions/'+plan['id']+'/build');build.raise_for_status();built=build.json()
                run=built['run'];row.update(artifact_id=built['design']['artifact_id'], run_id=run['id'], endpoint_path=built['design']['endpoint_path'], fingerprint=built['plan_fingerprint']);save()
                assert run['status']=='awaiting_approval'
                approved = api.post('/v1/runs/'+run['id']+'/decision',json={'approve':True,'plan_hash':run['plan_hash']});approved.raise_for_status()
                row['deployment_status']=approved.json()['status'];save()
                assert row['deployment_status']=='succeeded'
                tenant=settings.tenants()['sap-dev']
                oauth=httpx.post(tenant.token_url,auth=(credential('SAP_RUNTIME_CLIENT_ID'),credential('SAP_RUNTIME_CLIENT_SECRET')),data={'grant_type':'client_credentials'},timeout=30);oauth.raise_for_status()
                headers={'Authorization':'Bearer '+oauth.json()['access_token']}
                runtime=tenant.api_url.removesuffix('/api/v1').replace('-cpitrial06.','-cpitrial06-rt.')+'/http'+built['design']['endpoint_path']
                actual=httpx.post(runtime,headers=headers,json=case['sample_input'],timeout=60);actual.raise_for_status()
                assert actual.json()==case['expected_output'], 'SAP output does not match independent expected result'
                invalid=httpx.post(runtime,headers=headers,content='{broken',timeout=60)
                row.update(passed=True,http_status=actual.status_code,input=case['sample_input'],expected=case['expected_output'],actual=actual.json(),malformed_json_status=invalid.status_code)
                assert invalid.status_code==400
                save();print(case['name'], 'PASS', row['artifact_id'], flush=True)
            except Exception as error:
                row.update(passed=False,error=str(error));save();print(case['name'],'FAILED',str(error),flush=True)
    assert all(c.get('passed') for c in evidence['cases']), 'See acceptance report'

if __name__=='__main__':
    main()
