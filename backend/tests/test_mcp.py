import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_mcp_tool_discovery():
    async def check():
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
        async with stdio_client(StdioServerParameters(command=sys.executable,
            args=['-m', 'app.mcp_server'], env=env)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                names = {tool.name for tool in response.tools}
                assert names == {'list_packages', 'read_package', 'list_iflows', 'read_iflow',
                                 'runtime_status', 'message_logs', 'deployment_status', 'propose_run', 'inspect_run', 'service_capabilities', 'apim_proxies', 'aem_services', 'partner_parameters', 'diagnose_sap_apis', 'propose_order_design', 'compile_order_design'}
                propose = next(t for t in response.tools if t.name == 'propose_run')
                assert 'request' in propose.inputSchema['properties']
                assert not any('approve' in name or 'execute' in name for name in names)
    asyncio.run(check())
