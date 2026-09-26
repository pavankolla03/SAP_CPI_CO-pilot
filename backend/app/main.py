import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from .channels import Channels, BackgroundDecision
from .voice import Transcriber
from .scenarios import DescriptionRequest, describe, describe_orders
from . import solution_planner
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .agent import Agent
from .config import Settings
from .models import Decision, RunRequest, identifier
from .sap import SAPError
from .planner import FreePlanner, GoalRequest
from .capabilities import probe, service_inventory
from .diagnostics import preflight
from .messaging_designer import MessagingDesign, compile_messaging
from .order_designer import OrderDesignSpec, compile_orders, propose_orders
from .designer import ScenarioRequest, CompileRequest, propose as propose_design, compile_design, references


def create_app(settings=None):
    if settings is None:
        from dotenv import load_dotenv
        load_dotenv(override=False)
        settings = Settings()
    principals = settings.principals()
    agent = Agent(settings)
    planner = FreePlanner(settings)
    if any(p.tenant_id not in agent.tenants for p in principals.values()):
        raise ValueError('API key references unknown tenant')

    voice = Transcriber(settings)
    channels = Channels(settings, agent, planner, voice)

    @asynccontextmanager
    async def lifespan(app):
        channels.start()
        yield
        await run_in_threadpool(channels.close)
        agent.close()
        planner.close()

    app = FastAPI(title='SAP Integration Agent', version='0.1.0', lifespan=lifespan)
    app.state.channels = channels
    app.state.voice = voice
    app.state.agent = agent
    app.state.planner = planner
    if settings.extension_origin:
        app.add_middleware(CORSMiddleware, allow_origins=[settings.extension_origin],
                           allow_methods=['GET', 'POST'], allow_headers=['Authorization', 'Content-Type'])
    bearer = HTTPBearer(auto_error=False)

    def authenticated(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials:
            for token, principal in principals.items():
                if secrets.compare_digest(credentials.credentials, token):
                    return principal
        raise HTTPException(401, 'Valid bearer token required', headers={'WWW-Authenticate': 'Bearer'})

    def operator(principal=Depends(authenticated)):
        if principal.role not in ('operator', 'approver'):
            raise HTTPException(403, 'Operator role required')
        return principal

    def approver(principal=Depends(authenticated)):
        if principal.role != 'approver':
            raise HTTPException(403, 'Approver role required')
        return principal

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={'detail': str(error)})

    @app.exception_handler(KeyError)
    async def missing(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={'detail': 'Resource not found'})

    @app.exception_handler(SAPError)
    async def sap_error(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=error.status, content={'detail': str(error)})

    @app.middleware('http')
    async def guard_body(request: Request, call_next):
        # Count streamed bytes too; Content-Length alone does not protect chunked requests.
        if request.method == 'POST':
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 5_500_000:
                    from fastapi.responses import JSONResponse
                    return JSONResponse(status_code=413, content={'detail': 'Request too large'})
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/v1/me')
    def me(principal=Depends(authenticated)):
        tenant = agent.tenants[principal.tenant_id]
        return {**principal.model_dump(), 'tenant_name': tenant.name, 'mode': tenant.mode,
                'environment': tenant.environment, 'allow_upload': tenant.allow_upload or tenant.mode == 'demo'}

    @app.get('/v1/capabilities')
    def capabilities(principal=Depends(authenticated)):
        return probe(agent.tenants[principal.tenant_id], agent.clients[principal.tenant_id])

    @app.get('/v1/diagnostics')
    def diagnostics(principal=Depends(authenticated)):
        return preflight(agent.tenants[principal.tenant_id], agent.clients[principal.tenant_id])

    @app.get('/v1/apim/proxies')
    def apim(principal=Depends(authenticated)):
        return service_inventory(agent.tenants[principal.tenant_id], 'apim')

    @app.get('/v1/aem/services')
    def aem(principal=Depends(authenticated)):
        return service_inventory(agent.tenants[principal.tenant_id], 'aem')

    @app.get('/v1/b2b/parameters')
    def partners(principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].partner_parameters()

    @app.get('/v1/b2b/partners/{partner_id}/parameters/{parameter_id}')
    def partner(partner_id: str, parameter_id: str, principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].partner_parameter(identifier(partner_id), identifier(parameter_id))

    @app.get('/v1/planner')
    def planner_status(principal=Depends(authenticated)):
        return planner.status()

    @app.post('/v1/proposals')
    def proposal(body: GoalRequest, principal=Depends(operator)):
        return planner.propose(body.goal)

    @app.get('/v1/designs/knowledge')
    def design_knowledge(q: str = '', principal=Depends(authenticated)):
        return {'scope': 'Curated official references; not a live Discover catalog mirror', 'references': references(q)}

    @app.post('/v1/designs/propose')
    def design_proposal(body: ScenarioRequest, principal=Depends(operator)):
        return propose_design(body, planner)

    @app.post('/v1/designs/messaging/compile')
    def messaging_compile(body: MessagingDesign, principal=Depends(operator)):
        return compile_messaging(body)

    @app.post('/v1/designs/orders/propose')
    def order_proposal(body: ScenarioRequest, principal=Depends(operator)):
        return propose_orders(body, planner)

    @app.post('/v1/designs/orders/compile')
    def order_compile(body: OrderDesignSpec, principal=Depends(operator)):
        return compile_orders(body)

    @app.post('/v1/designs/compile')
    def design_compile(body: CompileRequest, principal=Depends(operator)):
        return compile_design(body)

    @app.get('/v1/packages')
    def packages(principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].packages()

    @app.get('/v1/packages/{package_id}')
    def package(package_id: str, principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].package(identifier(package_id))

    @app.get('/v1/packages/{package_id}/iflows')
    def flows(package_id: str, principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].flows(identifier(package_id))

    @app.get('/v1/iflows/{artifact_id}')
    def flow(artifact_id: str, version: str = 'active', principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].flow(identifier(artifact_id), identifier(version))

    @app.get('/v1/iflows/{artifact_id}/runtime')
    def runtime(artifact_id: str, principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].runtime(identifier(artifact_id))

    @app.get('/v1/iflows/{artifact_id}/mpl')
    def mpl(artifact_id: str, principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].mpl(identifier(artifact_id))

    @app.get('/v1/deployments/{task_id}')
    def build(task_id: str, principal=Depends(authenticated)):
        return agent.clients[principal.tenant_id].build(identifier(task_id))

    @app.get('/v1/runs')
    def runs(principal=Depends(authenticated)):
        return agent.store.query('SELECT id,created FROM runs WHERE tenant=? ORDER BY created DESC LIMIT 100',
                                 (principal.tenant_id,))

    @app.post('/v1/runs', status_code=201)
    def start(body: RunRequest, principal=Depends(operator)):
        return agent.start(body, principal)

    @app.get('/v1/runs/{run}')
    def run_view(run: str, principal=Depends(authenticated)):
        return agent.view(run, principal)

    @app.post('/v1/runs/{run}/decision')
    def decide(run: str, body: Decision, principal=Depends(approver)):
        return agent.decide(run, body, principal)

    @app.post('/v1/runs/{run}/resume')
    def resume(run: str, principal=Depends(approver)):
        return agent.resume(run, principal)

    @app.post('/v1/scenarios/orders')
    def scenario_orders(body: DescriptionRequest, principal=Depends(operator)):
        return describe_orders(body, principal, agent, planner)

    @app.post('/v1/solutions/analyze')
    def solution_analyze(body: DescriptionRequest, principal=Depends(operator)):
        return solution_planner.analyze(body, principal, agent, planner)

    @app.get('/v1/solutions/{plan_id}')
    def solution_read(plan_id: str, principal=Depends(authenticated)):
        return solution_planner.get_plan(plan_id, principal, agent)['public']

    @app.post('/v1/solutions/{plan_id}/build')
    def solution_build(plan_id: str, principal=Depends(operator)):
        return solution_planner.build(plan_id, principal, agent)

    @app.post('/v1/scenarios/compile')
    def scenario_compile(body: DescriptionRequest, principal=Depends(operator)):
        return describe(body, principal, agent, planner)

    @app.get('/v1/channels')
    def channel_status(principal=Depends(authenticated)):
        status = channels.status()
        # Do not expose the count of identities in other tenants.
        status['whatsapp']['linked_users'] = sum(p.tenant_id == principal.tenant_id for p in channels.links.values())
        return status

    @app.get('/v1/channel-jobs')
    def channel_jobs(principal=Depends(authenticated)):
        return channels.jobs(principal)

    @app.post('/v1/channel-jobs/decision', status_code=202)
    def background_decision(body: BackgroundDecision, principal=Depends(approver)):
        if not settings.channel_worker_enabled:
            raise HTTPException(503, 'Background worker is disabled')
        current = agent.view(body.run_id, principal)
        if not current.get('pending') or current.get('plan_hash') != body.plan_hash:
            raise HTTPException(409, 'No matching pending approval')
        key = f"decision:{principal.tenant_id}:{body.run_id}:{body.plan_hash}:{body.approve}"
        job = channels.enqueue('side-panel', key, principal, body.model_dump())
        return {'job_id': job, 'status': 'queued', 'run_id': body.run_id}

    @app.post('/v1/voice/transcribe')
    async def transcribe(request: Request, principal=Depends(operator)):
        if not request.headers.get('content-type','').startswith('audio/'):
            raise HTTPException(415, 'Send raw audio with an audio/* Content-Type')
        return await run_in_threadpool(voice.transcribe, await request.body())

    @app.get('/webhooks/whatsapp')
    def whatsapp_verify(request: Request):
        params = request.query_params
        if (not settings.whatsapp_enabled or not settings.whatsapp_verify_token
            or params.get('hub.mode') != 'subscribe'
            or not secrets.compare_digest(params.get('hub.verify_token',''), settings.whatsapp_verify_token)):
            raise HTTPException(403, 'Webhook verification failed')
        return PlainTextResponse(params.get('hub.challenge',''))

    @app.post('/webhooks/whatsapp')
    async def whatsapp_receive(request: Request):
        if not settings.whatsapp_enabled:
            raise HTTPException(503, 'WhatsApp is disabled')
        try:
            await run_in_threadpool(channels.webhook, await request.body(), request.headers.get('x-hub-signature-256',''))
        except PermissionError:
            raise HTTPException(401, 'Invalid webhook signature') from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(400, 'Webhook could not be accepted') from None
        return {'accepted': True}

    extension = Path(__file__).resolve().parents[2] / 'extension'
    app.mount('/ui', StaticFiles(directory=extension, html=True), name='side-panel-preview')

    @app.get('/', include_in_schema=False)
    def index():
        return RedirectResponse('/ui/')

    return app
