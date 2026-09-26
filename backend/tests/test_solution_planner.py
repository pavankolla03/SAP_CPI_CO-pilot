import json
from test_agent import TOKEN, OTHER, VIEWER


def install_planner(client, monkeypatch, mutate=None, pipeline_mutate=None, review=None):
    from app import solution_planner
    monkeypatch.setattr(solution_planner, 'research_references', lambda _: [])
    calls = []
    def propose(goal, schema, instructions):
        calls.append(schema.__name__)
        if schema.__name__ == 'CoverageReview':
            payload = json.loads(goal)
            complete = {'verdicts': [{'index': row['index'], 'covered': True, 'evidence': 'Typed operation present'}
                                     for row in payload['plan']['requirements']], 'questions': []}
            return {'draft': review(payload) if callable(review) else (review or complete), 'key_slot': 2}
        if schema.__name__ == 'PipelineDraft':
            request = json.loads(goal)
            design = {key: request[key] for key in ('package_id', 'artifact_id', 'endpoint_path')}
            design.update({'title': 'Normalize customer', 'required_fields': ['name'],
                           'mappings': [{'source': 'name', 'target': 'name', 'transform': 'uppercase'}]})
            if pipeline_mutate:
                pipeline_mutate(design)
            return {'draft': {'supported': True, 'explanation': 'Executable JSON pipeline',
                              'questions': [], 'design': design}, 'model': 'test:free', 'key_slot': 2}
        draft = {
            'title': 'Normalize customer', 'summary': 'Validate and uppercase the name.',
            'requirements': [{'description': 'Uppercase name', 'capability': 'mapping'}],
            'flows': [{'name': 'Normalize', 'purpose': 'Normalize customer name', 'sender': 'https',
                       'receiver': 'response', 'steps': ['Validate', 'Map name', 'Return JSON'], 'missing_configuration': []}],
            'questions': [], 'assumptions': [],
        }
        if mutate:
            mutate(draft)
        return {'draft': draft, 'model': 'test:free', 'key_slot': 1}
    monkeypatch.setattr(client.app.state.planner, 'propose', propose)
    return calls


def analyze(client, **updates):
    return client.post('/v1/solutions/analyze', json={
        'description': 'Receive HTTPS JSON, require name, uppercase name and return it.',
        'package_id': 'AgentSandbox', 'sample_input': {'name': 'Ada'}, 'expected_output': {'name': 'ADA'}, **updates})


def test_frozen_plan_build_and_approval(client, monkeypatch):
    calls = install_planner(client, monkeypatch)
    result = analyze(client)
    assert result.status_code == 200, result.text
    plan = result.json()
    assert plan['buildable'] and plan['acceptance']['status'] == 'passed_locally'
    assert client.get('/v1/runs').json() == []  # planning cannot create a deployment
    build = client.post('/v1/solutions/' + plan['id'] + '/build').json()
    assert build['run']['status'] == 'awaiting_approval'
    assert calls == ['SolutionDraft', 'PipelineDraft', 'CoverageReview']  # no generation at build
    assert client.get('/v1/iflows/' + build['design']['artifact_id']).status_code == 404
    again = client.post('/v1/solutions/' + plan['id'] + '/build').json()
    assert again['run']['id'] == build['run']['id'] and again['artifact_content'] == build['artifact_content']
    run = build['run']
    approved = client.post('/v1/runs/' + run['id'] + '/decision', json={'approve': True, 'plan_hash': run['plan_hash']})
    assert approved.json()['status'] == 'succeeded'
    assert client.post('/v1/solutions/' + plan['id'] + '/build').json()['run']['status'] == 'succeeded'


def test_plan_isolation_and_roles(client, monkeypatch):
    install_planner(client, monkeypatch)
    plan = analyze(client).json()
    client.headers['Authorization'] = 'Bearer ' + OTHER
    assert client.get('/v1/solutions/' + plan['id']).status_code == 404
    assert client.post('/v1/solutions/' + plan['id'] + '/build').status_code == 404
    client.headers['Authorization'] = 'Bearer ' + VIEWER
    assert client.get('/v1/solutions/' + plan['id']).status_code == 200
    assert client.post('/v1/solutions/' + plan['id'] + '/build').status_code == 403
    assert analyze(client).status_code == 403
    client.headers['Authorization'] = 'Bearer ' + TOKEN


def test_unsupported_adapter_cannot_be_marked_buildable(client, monkeypatch):
    def external(draft):
        draft['requirements'].append({'description': 'Upsert in SuccessFactors', 'capability': 'odata_receiver'})
        draft['flows'][0]['receiver'] = 'odata'
    install_planner(client, monkeypatch, external)
    plan = analyze(client).json()
    assert not plan['buildable']
    assert 'odata' in ' '.join(plan['blockers'])
    assert client.post('/v1/solutions/' + plan['id'] + '/build').status_code == 409
    assert client.get('/v1/runs').json() == []


def test_semantic_omission_and_wrong_output_block_build(client, monkeypatch):
    install_planner(client, monkeypatch, review=lambda payload: {
        'verdicts': [{'index': row['index'], 'covered': False, 'evidence': 'Routing threshold was omitted'}
                     for row in payload['plan']['requirements']], 'questions': []})
    assert not analyze(client).json()['buildable']
    install_planner(client, monkeypatch)
    mismatch = analyze(client, expected_output={'name': 'WRONG'}).json()
    assert not mismatch['buildable'] and any('Acceptance' in b for b in mismatch['blockers'])


def test_missing_rule_and_multi_flow_do_not_fall_back(client, monkeypatch):
    def clarify(draft):
        draft['questions'] = ['What total requires review?']
    install_planner(client, monkeypatch, clarify)
    plan = analyze(client).json()
    assert plan['status'] == 'needs_answers' and not plan['buildable']
    def modular(draft):
        draft['flows'].append({**draft['flows'][0], 'name': 'Second flow'})
    install_planner(client, monkeypatch, modular)
    plan = analyze(client).json()
    assert not plan['buildable'] and len(plan['flows']) == 2


def test_target_substitution_and_missing_operation_rejected(client, monkeypatch):
    def retarget(draft):
        draft['package_id'] = 'OtherPackage'
    install_planner(client, monkeypatch, pipeline_mutate=retarget)
    assert analyze(client).status_code == 409
    def missing(draft):
        draft['requirements'].append({'description': 'Route by total', 'capability': 'router'})
    install_planner(client, monkeypatch, missing)
    assert not analyze(client).json()['buildable']


def test_conditional_status_mislabeled_as_calculation_uses_router(client, monkeypatch):
    def conditional(draft):
        draft['requirements'].append({'description': 'Set status to PREMIUM if price is above 100, otherwise STANDARD',
                                      'capability': 'calculation'})
    def with_route(design):
        design['routes'] = [{'condition': {'source': 'name', 'operator': 'eq', 'value': 'VIP'}, 'label': 'PREMIUM'}]
        design['default_route'] = 'STANDARD'
    install_planner(client, monkeypatch, conditional, pipeline_mutate=with_route)
    assert analyze(client, expected_output={'name': 'ADA', 'status': 'STANDARD'}).json()['buildable']


def test_price_comparison_for_routing_is_not_numeric_calculation(client, monkeypatch):
    def conditional(draft):
        draft['requirements'].append({'description': 'Calculate price comparison to 100 for routing',
                                      'capability': 'calculation'})
    def with_route(design):
        design['routes'] = [{'condition': {'source': 'name', 'operator': 'eq', 'value': 'VIP'}, 'label': 'PREMIUM'}]
        design['default_route'] = 'STANDARD'
    install_planner(client, monkeypatch, conditional, pipeline_mutate=with_route)
    assert analyze(client, expected_output={'name': 'ADA', 'status': 'STANDARD'}).json()['buildable']
