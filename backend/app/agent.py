"""Constrained, deterministic agent. All external writes are graph-owned and approved."""
import json
import sqlite3
import threading
import time
from typing import TypedDict
from uuid import uuid4

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    _CHECKPOINTER = 'sqlite'
except ImportError:
    try:
        from langgraph.checkpoint import SqliteSaver  # older path
        _CHECKPOINTER = 'sqlite'
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver
        _CHECKPOINTER = 'memory'

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .models import digest, inspect_bundle
from .sap import DemoClient, SAPClient, SAPError
from .store import Store, now


class State(TypedDict, total=False):
    id: str
    tenant: str
    request: dict
    plan: dict
    plan_hash: str
    status: str
    approved: bool
    attempt: int
    deployment: dict
    observation: dict
    valid: bool
    test: dict
    error: str


class Agent:
    def __init__(self, settings):
        from pathlib import Path
        self.settings = settings
        self.tenants = settings.tenants()
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        self.store = Store(str(Path(settings.data_dir) / 'app.sqlite'))
        if _CHECKPOINTER == 'sqlite':
            self.connection = sqlite3.connect(str(Path(settings.data_dir) / 'checkpoints.sqlite'), check_same_thread=False)
            self.saver = SqliteSaver(self.connection)
        else:
            self.saver = MemorySaver()
        self.clients = {key: DemoClient(t, self.store) if t.mode == 'demo' else SAPClient(t)
                        for key, t in self.tenants.items()}
        self.lock = threading.Lock()  # This MVP runs exactly one API process/worker.
        graph = StateGraph(State)
        for name in ('discover', 'plan', 'approve', 'execute', 'observe', 'validate', 'test', 'fix', 'redeploy', 'verify', 'audit'):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, 'discover')
        graph.add_edge('discover', 'plan')
        graph.add_edge('plan', 'approve')
        graph.add_conditional_edges('approve', lambda s: 'execute' if s['approved'] else 'audit')
        graph.add_edge('execute', 'observe')
        graph.add_edge('observe', 'validate')
        graph.add_conditional_edges('validate', lambda s: 'test' if s['valid'] else 'fix')
        graph.add_conditional_edges('test', lambda s: 'verify' if s['valid'] else 'fix')
        graph.add_conditional_edges('fix', lambda s: 'redeploy' if s['approved'] else 'audit')
        graph.add_edge('redeploy', 'observe')
        graph.add_edge('verify', 'audit')
        graph.add_edge('audit', END)
        self.graph = graph.compile(checkpointer=self.saver)

    def close(self):
        for client in self.clients.values():
            client.close()
        if hasattr(self, 'connection') and self.connection:
            self.connection.close()
        self.store.db.close()

    @staticmethod
    def config(run):
        return {'configurable': {'thread_id': run}, 'recursion_limit': 40}

    def event(self, s, phase, **details):
        self.store.event(s['id'], phase, details)

    def existing(self, fn, *args):
        try:
            return fn(*args)
        except SAPError as error:
            if error.status == 404:
                return None
            raise

    def snapshot(self, s):
        client, request = self.clients[s['tenant']], s['request']
        if request['action'] == 'create_partner_parameter':
            return {'partner_parameter': self.existing(client.partner_parameter, request['partner_id'], request['parameter_id'])}
        return {'package': self.existing(client.package, request['package_id']),
                'artifact': None if request['action'] == 'create_package' else
                self.existing(client.flow, request['artifact_id'], request['version'])}

    def discover(self, s):
        client = self.clients[s['tenant']]
        if s['request']['action'] == 'create_package':
            client.packages()  # Prove the collection exists before treating an entity 404 as absence.
        elif s['request']['action'] == 'create_partner_parameter':
            client.partner_parameters()
        before = self.snapshot(s)
        request = s['request']
        if request['action'] == 'create_partner_parameter':
            if before['partner_parameter']:
                raise ValueError('Partner parameter already exists; overwrite is not supported')
            self.event(s, 'discover', partner_id=request['partner_id'])
            return {'plan': {'before': before}, 'attempt': 0}
        if request['action'] == 'create_package' and before['package']:
            raise ValueError('Package already exists; choose a new ID')
        if request['action'] != 'create_package' and not before['package']:
            raise ValueError('Create the target package first')
        if request['action'] == 'deploy' and not before['artifact']:
            raise ValueError('Artifact not found')
        if request['action'] == 'deploy' and before['artifact'].get('PackageId') != request['package_id']:
            raise ValueError('Artifact does not belong to the selected package')
        if request['action'] in ('upload','upload_deploy'):
            if before['artifact']:
                raise ValueError('MVP upload only creates new IDs; overwriting requires a later update workflow')
            tenant = self.tenants[s['tenant']]
            if tenant.mode == 'sap' and not tenant.allow_upload:
                raise ValueError('Upload is disabled; administrator must enable it after checking tenant support')
            if request['version'] != 'active':
                raise ValueError('New uploads must deploy version active')
        self.event(s, 'discover', package=request['package_id'], artifact=request['artifact_id'])
        return {'plan': {'before': before}, 'attempt': 0}

    def plan(self, s):
        request = s['request']
        action = request['action']
        bundle = inspect_bundle(request['artifact_content']) if request.get('artifact_content') else None
        operations = {'create_partner_parameter': ['create_partner_parameter'], 'create_package': ['create_package'], 'deploy': ['deploy'],
                      'upload': ['upload'], 'upload_deploy': ['upload', 'deploy']}[action]
        plan = {'before': s['plan']['before'], 'operations': operations, 'environment': 'DEV',
                'tenant': s['tenant'], 'goal': request['goal'], 'bundle': bundle,
                'after': {'package_id': request['package_id'], 'artifact_id': request['artifact_id'],
                          'name': request['name'], 'version': request['version'], 'action': action},
                'risk': 'Creates DEV content' if action == 'create_package' else
                        'Deploys executable integration code; may trigger schedules and external side effects',
                'test_scope': 'Package read-back' if action == 'create_package' else
                              'Deployment/runtime smoke test. No business message is sent.'}
        if action == 'upload':
            plan['risk'] = 'Creates an undeployed DEV design artifact; does not activate messaging consumers'
            plan['test_scope'] = 'Design-time read-back only; deployment and broker delivery remain untested'
        if action == 'create_partner_parameter':
            plan['after'] = {key: request[key] for key in ('partner_id', 'parameter_id', 'parameter_value', 'action')}
            plan['risk'] = 'Creates partner configuration; existing integrations may read this value'
            plan['test_scope'] = 'Read-back of the exact partner parameter; no B2B message is sent'
        self.event(s, 'plan', operations=operations, plan_hash=digest(plan))
        return {'plan': plan, 'plan_hash': digest(plan), 'status': 'awaiting_approval'}

    def approve(self, s):
        decision = interrupt({'kind': 'approval', 'plan_hash': s['plan_hash'], 'plan': s['plan']})
        self.event(s, 'approve', actor=decision['actor'], approved=decision['approve'], plan_hash=s['plan_hash'])
        return {'approved': decision['approve'], 'status': 'running' if decision['approve'] else 'rejected'}

    def execute(self, s):
        if not s['approved'] or digest(s['plan']) != s['plan_hash']:
            raise ValueError('Valid approval required')
        # Preflight itself is journaled: resuming a partially executed node must not mistake
        # its own completed package/upload operation for a pre-approval external change.
        def preflight():
            if digest(self.snapshot(s)) != digest(s['plan']['before']):
                raise ValueError('SAP content changed after planning; create a new plan')
            return {'checked': True}
        self.store.once(s['id'] + ':preflight', preflight)
        client = self.clients[s['tenant']]
        deployment = {}
        for operation in s['plan']['operations']:
            result = self.store.once(s['id'] + ':' + operation, lambda op=operation: getattr(client, op)(s['request']))
            if operation == 'deploy':
                deployment = result
            self.event(s, 'execute', tool=operation, outcome='completed')
        return {'deployment': deployment}

    def observe(self, s):
        client = self.clients[s['tenant']]
        if s['request']['action'] == 'create_partner_parameter':
            observation = {'partner_parameter': client.partner_parameter(s['request']['partner_id'], s['request']['parameter_id'])}
        elif s['request']['action'] == 'create_package':
            observation = {'package': client.package(s['request']['package_id'])}
        elif s['request']['action'] == 'upload':
            observation = {'artifact': client.flow(s['request']['artifact_id'])}
        else:
            build = {}
            runtime = None
            for index in range(self.settings.poll_attempts):
                build = client.build(s['deployment']['task_id'])
                status = str(build.get('Status', '')).upper()
                if status == 'SUCCESS':
                    runtime = self.existing(client.runtime, s['request']['artifact_id'])
                    if runtime and runtime.get('Status') == 'STARTED':
                        break
                if status in ('Failed', 'Error', 'ERROR', 'FAILED', 'FAIL'):
                    break
                if index + 1 < self.settings.poll_attempts:
                    time.sleep(self.settings.poll_seconds)
            try:
                mpl = client.mpl(s['request']['artifact_id'])
                mpl_error = None
            except SAPError:
                mpl, mpl_error = [], 'MPL unavailable; check monitoring permissions'
            observation = {'build': build, 'runtime': runtime, 'mpl': mpl, 'mpl_error': mpl_error}
        self.event(s, 'observe', observation=observation)
        return {'observation': observation}

    def validate(self, s):
        observation = s['observation']
        if s['request']['action'] == 'create_partner_parameter':
            row = observation.get('partner_parameter', {})
            valid = all(row.get(k) == s['request'][v] for k, v in [('Pid', 'partner_id'), ('Id', 'parameter_id'), ('Value', 'parameter_value')])
            self.event(s, 'validate', passed=valid)
            return {'valid': valid}
        if s['request']['action'] == 'upload':
            row = observation.get('artifact', {})
            valid = row.get('Id') == s['request']['artifact_id'] and row.get('PackageId') == s['request']['package_id']
            self.event(s, 'validate', passed=valid)
            return {'valid': valid}
        valid = (observation.get('package', {}).get('Id') == s['request']['package_id']
                 if s['request']['action'] == 'create_package' else
                 str(observation['build'].get('Status', '')).upper() == 'SUCCESS' and
                 (observation.get('runtime') or {}).get('Status') == 'STARTED')
        self.event(s, 'validate', passed=valid)
        return {'valid': valid}

    def test(self, s):
        request = s['request']
        if request['action'] == 'create_partner_parameter':
            path, field, expected = f"/v1/b2b/partners/{request['partner_id']}/parameters/{request['parameter_id']}", 'Value', request['parameter_value']
        elif request['action'] == 'create_package':
            path, field, expected = f"/v1/packages/{request['package_id']}", 'Id', request['package_id']
        elif request['action'] == 'upload':
            path, field, expected = f"/v1/iflows/{request['artifact_id']}", 'Id', request['artifact_id']
        else:
            path, field, expected = f"/v1/iflows/{request['artifact_id']}/runtime", 'Status', 'STARTED'
        code = ("import os\nimport httpx\n\ndef test_dev_smoke():\n"
                f"    response = httpx.get(os.environ['AGENT_URL'] + {path!r},\n"
                "        headers={'Authorization': 'Bearer ' + os.environ['AGENT_TOKEN']}, timeout=30)\n"
                "    response.raise_for_status()\n"
                f"    assert response.json()[{field!r}] == {expected!r}\n")
        client = self.clients[s['tenant']]
        if request['action'] == 'create_partner_parameter':
            result = client.partner_parameter(request['partner_id'], request['parameter_id'])
        elif request['action'] == 'upload':
            result = client.flow(request['artifact_id'])
        else:
            result = client.package(request['package_id']) if request['action'] == 'create_package' else client.runtime(request['artifact_id'])
        passed = result.get(field) == expected
        self.event(s, 'test', passed=passed, scope='read-only smoke assertion')
        return {'test': {'code': code, 'passed': passed, 'scope': 'read-only smoke; business scenario untested'}, 'valid': passed}

    def fix(self, s):
        build_status = s['observation'].get('build', {}).get('Status')
        if s['request']['action'] != 'deploy' or s['attempt'] >= 1 or build_status not in ('Failed', 'Error', 'ERROR', 'FAILED', 'FAIL'):
            self.event(s, 'fix', action='manual_review', reason='Retry limit or deployment not conclusively failed')
            return {'approved': False, 'status': 'needs_attention'}
        # Bounded remediation: one explicitly approved redeploy of the SAME design-time snapshot.
        decision = interrupt({'kind': 'repair_approval', 'plan_hash': s['plan_hash'],
            'message': 'Build failed. Retry this same artifact once, or reject and submit a corrected ZIP under a new ID.'})
        self.event(s, 'fix', actor=decision['actor'], approved=decision['approve'], action='retry_same_artifact')
        return {'approved': decision['approve'], 'status': 'running' if decision['approve'] else 'needs_attention'}

    def redeploy(self, s):
        client = self.clients[s['tenant']]
        # For uploaded artifacts, do not auto-retry because there is no trustworthy before snapshot.
        if s['request']['action'] != 'deploy' or digest(self.snapshot(s)) != digest(s['plan']['before']):
            raise ValueError('Remediation needs a new plan for uploaded or changed content')
        result = self.store.once(s['id'] + ':redeploy', lambda: client.deploy(s['request']))
        self.event(s, 'redeploy', attempt=1)
        return {'deployment': result, 'attempt': 1}

    def verify(self, s):
        self.event(s, 'verify', passed=s['valid'], business_tested=False)
        return {'status': 'succeeded' if s['valid'] else 'needs_attention'}

    def audit(self, s):
        self.event(s, 'audit', status=s['status'], plan_hash=s.get('plan_hash'), mode=self.tenants[s['tenant']].mode)
        return {}

    def owner(self, run, principal):
        rows = self.store.query('SELECT * FROM runs WHERE id=? AND tenant=?', (run, principal.tenant_id))
        if not rows:
            raise KeyError('Run not found')

    def view(self, run, principal):
        self.owner(run, principal)
        state = self.graph.get_state(self.config(run))
        values = dict(state.values)
        values.pop('request', None)  # ZIP data is not returned in run polling responses.
        values.pop('approved', None)
        pending = [i.value for task in state.tasks for i in task.interrupts]
        values['pending'] = pending
        if pending:
            values['status'] = 'awaiting_repair' if pending[0]['kind'] == 'repair_approval' else 'awaiting_approval'
        values['events'] = [{**r, 'data': json.loads(r['data'])} for r in self.store.query(
            'SELECT seq,phase,at,data FROM events WHERE run=? ORDER BY seq', (run,))]
        return values

    def invoke(self, run, value):
        try:
            self.graph.invoke(value, self.config(run))
        except (SAPError, ValueError) as error:
            self.store.event(run, 'error', {'message': str(error)})
            self.store.event(run, 'audit', {'status': 'needs_attention', 'reason': 'execution_halted'})
            self.graph.update_state(self.config(run), {'status': 'needs_attention', 'error': str(error)})
        except Exception:
            self.store.event(run, 'error', {'message': 'Unexpected backend failure; inspect server diagnostics'})
            self.graph.update_state(self.config(run), {'status': 'needs_attention', 'error': 'Unexpected backend failure'})
            raise

    def start(self, request, principal):
        if not self.lock.acquire(blocking=False):
            raise ValueError('Agent is busy; retry after the current operation completes')
        try:
            run = str(uuid4())
            self.store.query('INSERT INTO runs VALUES(?,?,?)', (run, principal.tenant_id, now()))
            self.store.event(run, 'requested', {'actor': principal.actor})
            self.invoke(run, {'id': run, 'tenant': principal.tenant_id, 'request': request.model_dump(), 'status': 'running'})
            return self.view(run, principal)
        finally:
            self.lock.release()

    def decide(self, run, decision, principal):
        if not self.lock.acquire(blocking=False):
            raise ValueError('Agent is busy; retry later')
        try:
            current = self.view(run, principal)
            if not current['pending'] or current['plan_hash'] != decision.plan_hash:
                raise ValueError('No matching pending approval')
            self.invoke(run, Command(resume={**decision.model_dump(), 'actor': principal.actor}))
            return self.view(run, principal)
        finally:
            self.lock.release()

    def resume(self, run, principal):
        if not self.lock.acquire(blocking=False):
            raise ValueError('Agent is busy; retry later')
        try:
            self.owner(run, principal)
            state = self.graph.get_state(self.config(run))
            if not state.next or any(task.interrupts for task in state.tasks):
                raise ValueError('Run is complete or needs a decision')
            self.invoke(run, None)
            return self.view(run, principal)
        finally:
            self.lock.release()
