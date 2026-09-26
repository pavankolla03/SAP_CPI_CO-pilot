"""Read-only diagnostics. Run from repository root with PYTHONPATH=backend."""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from app.agent import Agent
from app.capabilities import probe
from app.config import Settings
from app.diagnostics import preflight

parser = argparse.ArgumentParser(description='Check configured service access without mutations')
parser.add_argument('--tenant', required=True)
parser.add_argument('--output', default='data/connection-check.json')
args = parser.parse_args()
load_dotenv(override=False)
agent = Agent(Settings())
try:
    if args.tenant not in agent.tenants:
        raise SystemExit('Unknown configured tenant')
    result = probe(agent.tenants[args.tenant], agent.clients[args.tenant])
    result['preflight'] = preflight(agent.tenants[args.tenant], agent.clients[args.tenant])
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    for row in result['results']:
        print(f"{row['capability']}: {row['status']} — {row['detail']}")
    for row in result['preflight']['checks']:
        print(f"{row['name']}: {row['status']} — {row['detail']}")
finally:
    agent.close()
