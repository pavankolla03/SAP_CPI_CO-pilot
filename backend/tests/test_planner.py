import json

import httpx
import pytest

from app.config import Settings
from app.planner import FreePlanner

MODEL = 'test/model:free'
DRAFT = {'action':'deploy','package_id':'Sandbox','artifact_id':'Echo','version':'active','name':'Echo','explanation':'Deploy the requested artifact'}


def make(monkeypatch, responder, model=MODEL):
    monkeypatch.setenv('OPENROUTER_API_KEY_1', 'slot-one')
    monkeypatch.setenv('OPENROUTER_API_KEY_2', 'slot-two')
    def handler(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200, json={'data':[{'id':MODEL,'pricing':{'prompt':'0','completion':'0'}}]})
        return responder(request)
    return FreePlanner(Settings(_env_file=None,llm_enabled=True,llm_models=model),httpx.MockTransport(handler))


def completion(draft=DRAFT):
    return httpx.Response(200,json={'model':MODEL,'choices':[{'message':{'content':json.dumps(draft)}}], 'usage':{'cost':0}})


def test_free_only_key_rotation_and_typed_proposal(monkeypatch):
    seen=[]
    def handler(request):
        seen.append(request.headers['Authorization'])
        data=json.loads(request.content)
        assert data['provider']['max_price']=={'prompt':0,'completion':0}
        assert all(m.endswith(':free') for m in data['models'])
        assert 'slot-one' not in request.content.decode()
        return completion()
    planner=make(monkeypatch,handler)
    first=planner.propose('Deploy artifact_id Echo package_id Sandbox')
    second=planner.propose('Deploy artifact_id Echo package_id Sandbox')
    assert first['approval_required'] and second['cost']==0
    assert seen==['Bearer slot-one','Bearer slot-two']
    planner.close()


def test_paid_or_missing_model_blocks_before_completion(monkeypatch):
    def handler(request):
        pytest.fail('Completion must not be sent')
    planner=make(monkeypatch,handler,model='expensive/paid-model')
    with pytest.raises(ValueError,match='not verified zero-cost'):
        planner.propose('Create package ID Test')
    planner.close()


def test_rate_limit_cools_down_all_keys(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'120'})
    planner=make(monkeypatch,handler)
    with pytest.raises(ValueError,match='rate limited'):
        planner.propose('Create package ID Test')
    with pytest.raises(ValueError,match='cooldown'):
        planner.propose('Create package ID Test')
    assert len(calls)==1
    planner.close()


@pytest.mark.parametrize('draft', [{**DRAFT,'approve':True},{**DRAFT,'action':'delete'},
    {**DRAFT,'artifact_id':"bad')"},{**DRAFT,'tenant_id':'other'}, {**DRAFT,'artifact_id':''}])
def test_untrusted_model_output_cannot_expand_authority(monkeypatch,draft):
    planner=make(monkeypatch,lambda request:completion(draft))
    with pytest.raises(ValueError):
        planner.propose('Deploy artifact Echo in package Sandbox')
    planner.close()


def test_unsupported_proposal_is_not_a_run(monkeypatch):
    planner=make(monkeypatch,lambda request:completion({**DRAFT,'action':'unsupported'}))
    assert planner.propose('Delete production packages')['supported'] is False
    planner.close()


def test_secret_goal_never_sent(monkeypatch):
    planner=make(monkeypatch,lambda request:pytest.fail('Must not send credentials'))
    with pytest.raises(ValueError,match='Remove credentials'):
        planner.propose('My clientsecret is abc')
    planner.close()


def test_provider_errors_sanitized(monkeypatch):
    planner=make(monkeypatch,lambda request:httpx.Response(401,json={'error':'secret internal upstream response'}))
    with pytest.raises(ValueError,match='HTTP 401') as error:
        planner.propose('Create package ID Test')
    assert 'secret' not in str(error.value)
    planner.close()


def test_one_format_retry_then_valid_proposal(monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        if len(calls)==1:
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"action":'}}]})
        return completion()
    planner=make(monkeypatch,respond)
    assert planner.propose('Deploy Echo in Sandbox')['supported']
    assert len(calls)==2
    planner.close()


def test_format_retry_is_bounded_and_does_not_retry_rate_limit(monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'invalid'}}]})
    planner=make(monkeypatch,respond)
    with pytest.raises(ValueError,match='invalid proposal'):
        planner.propose('Deploy Echo in Sandbox')
    assert len(calls)==2
    planner.close()
