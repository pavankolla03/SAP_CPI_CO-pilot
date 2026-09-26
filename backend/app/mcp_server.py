"""stdio MCP facade; all authority comes from a server-side scoped API token.
No approve tool: an LLM/MCP client cannot grant itself approval.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

from .models import RunRequest, identifier
from .designer import ScenarioRequest
from .order_designer import OrderDesignSpec

mcp = FastMCP('SAP Integration DEV Agent')


def call(method, path, body=None):
    token = os.environ['AGENT_TOKEN']
    base = os.environ.get('AGENT_URL', 'http://127.0.0.1:8000')
    with httpx.Client(base_url=base, timeout=90, follow_redirects=False) as client:
        response = client.request(method, path, json=body, headers={'Authorization': f'Bearer {token}'})
        response.raise_for_status()
        return response.json()


@mcp.tool()
def list_packages() -> list:
    """List integration packages for the authenticated DEV tenant."""
    return call('GET', '/v1/packages')


@mcp.tool()
def read_package(package_id: str) -> dict:
    """Read one integration package."""
    return call('GET', f'/v1/packages/{identifier(package_id)}')


@mcp.tool()
def list_iflows(package_id: str) -> list:
    """List design-time iFlows in a package."""
    return call('GET', f'/v1/packages/{identifier(package_id)}/iflows')


@mcp.tool()
def read_iflow(artifact_id: str) -> dict:
    """Read active design-time iFlow metadata."""
    return call('GET', f'/v1/iflows/{identifier(artifact_id)}')


@mcp.tool()
def runtime_status(artifact_id: str) -> dict:
    """Read deployment runtime status."""
    return call('GET', f'/v1/iflows/{identifier(artifact_id)}/runtime')


@mcp.tool()
def message_logs(artifact_id: str) -> list:
    """Read the latest 20 message log summaries without payloads."""
    return call('GET', f'/v1/iflows/{identifier(artifact_id)}/mpl')


@mcp.tool()
def deployment_status(task_id: str) -> dict:
    """Read a build/deployment task."""
    return call('GET', f'/v1/deployments/{identifier(task_id)}')


@mcp.tool()
def propose_run(request: RunRequest) -> dict:
    """Propose package creation, deployment, or ZIP upload+deployment; pauses for human approval."""
    return call('POST', '/v1/runs', request.model_dump())


@mcp.tool()
def inspect_run(run_id: str) -> dict:
    """Read a plan, pending approval, and execution timeline."""
    return call('GET', f'/v1/runs/{identifier(run_id)}')


@mcp.tool()
def service_capabilities() -> dict:
    """Check configured service access without writing anything."""
    return call('GET', '/v1/capabilities')


@mcp.tool()
def apim_proxies() -> dict:
    """Read first page of API Management proxies using a separate APIM connection."""
    return call('GET', '/v1/apim/proxies')


@mcp.tool()
def aem_services() -> dict:
    """Read first page of Advanced Event Mesh services using a separate AEM connection."""
    return call('GET', '/v1/aem/services')


@mcp.tool()
def partner_parameters() -> list:
    """List partner directory parameter identifiers, without values."""
    return call('GET', '/v1/b2b/parameters')


@mcp.tool()
def diagnose_sap_apis() -> dict:
    """Read-only API preflight; does not prove write access or return message payloads."""
    return call('GET', '/v1/diagnostics')


@mcp.tool()
def propose_order_design(request: ScenarioRequest) -> dict:
    """Interpret a batch order scenario with a free model. Does not change SAP."""
    return call('POST', '/v1/designs/orders/propose', request.model_dump())


@mcp.tool()
def compile_order_design(design: OrderDesignSpec) -> dict:
    """Generate a native HTTPS/Splitter/Router/Gather/Exception iFlow ZIP; does not deploy."""
    return call('POST', '/v1/designs/orders/compile', design.model_dump())


if __name__ == '__main__':
    mcp.run()
