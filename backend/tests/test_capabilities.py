import httpx
import pytest

from app.capabilities import ServiceReader
from app.config import ServiceConnection
from test_agent import plan, decide, OTHER


def test_partner_create_readback_and_isolation(client):
    run=plan(client,action='create_partner_parameter',partner_id='TestPartner',parameter_id='Greeting',parameter_value='hello')
    result=decide(client,run).json()
    assert result['status']=='succeeded'
    assert result['test']['passed']
    assert client.get('/v1/b2b/partners/TestPartner/parameters/Greeting').json()['Value']=='hello'
    assert client.get('/v1/b2b/parameters').json()==[{'Pid':'TestPartner','Id':'Greeting'}]
    assert plan(client,action='create_partner_parameter',partner_id='TestPartner',parameter_id='Greeting')['status']=='needs_attention'
    client.headers['Authorization']='Bearer '+OTHER
    assert client.get('/v1/b2b/parameters').json()==[]


def test_partner_rejection(client):
    run=plan(client,action='create_partner_parameter')
    assert decide(client,run,False).json()['status']=='rejected'
    assert client.get('/v1/b2b/parameters').json()==[]


def test_capability_status_does_not_fake_missing_connections(client):
    rows={row['capability']:row['status'] for row in client.get('/v1/capabilities').json()['results']}
    assert rows=={'cloud_integration':'accessible','b2b_partner_directory':'accessible','apim':'not_configured','aem':'not_configured','b2b_tpm':'not_implemented'}
    assert client.get('/v1/apim/proxies').status_code==409
    assert client.get('/v1/aem/services').status_code==409


def test_apim_oauth_contract(monkeypatch):
    monkeypatch.setenv('APIM_ID','apim-id')
    monkeypatch.setenv('APIM_SECRET','apim-secret')
    connection=ServiceConnection(api_url='https://apim.example',token_url='https://auth.example/token',client_id_env='APIM_ID',client_secret_env='APIM_SECRET')
    def handle(request):
        if request.url.host=='auth.example':
            return httpx.Response(200,json={'access_token':'apim-token'})
        assert request.headers['Authorization']=='Bearer apim-token'
        assert request.url.path=='/apiportal/api/1.0/Management.svc/APIProxies'
        return httpx.Response(200,json={'d':{'results':[]}})
    reader=ServiceReader(connection,httpx.MockTransport(handle))
    assert reader.read('/apiportal/api/1.0/Management.svc/APIProxies')['d']['results']==[]


def test_aem_bearer_contract(monkeypatch):
    monkeypatch.setenv('AEM_TOKEN','aem-token')
    connection=ServiceConnection(api_url='https://aem.example',api_token_env='AEM_TOKEN')
    def handle(request):
        assert request.headers['Authorization']=='Bearer aem-token'
        assert request.url.path=='/api/v2/missionControl/eventBrokerServices'
        return httpx.Response(200,json={'data':[{'id':'service-1'}]})
    assert ServiceReader(connection,httpx.MockTransport(handle)).read('/api/v2/missionControl/eventBrokerServices')['data'][0]['id']=='service-1'


@pytest.mark.parametrize('url',['http://aem.example','https://user:pass@aem.example','https://aem.example?token=x'])
def test_unsafe_service_configuration_rejected(url):
    with pytest.raises(ValueError):
        ServiceConnection(api_url=url,api_token_env='AEM_TOKEN')
