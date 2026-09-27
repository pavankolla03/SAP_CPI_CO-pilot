"""Multi-scenario orchestrator for complex SAP integration goals.

Analyzes a natural-language goal and proposes a decomposed set of coordinated
integration artifacts, routes between them, and an integration diagram.
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from .designer import StrictModel
from .models import identifier


class FlowRelationship(StrictModel):
    from_artifact: str
    to_artifact: str
    channel: Literal["ProcessDirect", "JMS", "HTTP", "Solace", "SFTP", "File"]
    direction: Literal["request", "response", "async", "broadcast"] = "request"


class FlowProposal(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    package_id: str
    pattern: Literal["https", "soap", "odata", "sftp", "file", "jms", "messaging", "api_proxy", "b2b"]
    steps: list[str] = Field(min_length=1, max_length=12)
    depends_on: list[str] = Field(default_factory=list, max_length=10)


class DecompositionResult(StrictModel):
    supported: bool
    explanation: str = Field(max_length=2000)
    flows: list[FlowProposal] = Field(max_length=8)
    relationships: list[FlowRelationship] = Field(max_length=12)
    diagram: str = Field(default="", max_length=4000)
    questions: list[str] = Field(max_length=8)


def propose_decomposition(goal, package_id: str, planner=None) -> dict:
    """Propose a decomposition of a complex goal into coordinated artifacts."""
    if planner is None:
        raise ValueError('planner is required; pass the FastAPI planner from main.py')
    instructions = (
        "Decompose complex SAP integration goals into a small number of coordinated artifacts. "
        "Prefer ProcessDirect between internal flows, JMS for async, and HTTP/REST for external. "
        "Do not create more than 8 artifacts. Return typed DecompositionResult."
    )
    request = {"goal": goal, "package_id": package_id}
    response = planner.propose(json.dumps(request), schema=DecompositionResult, instructions=instructions)
    result = DecompositionResult.model_validate(response["draft"])
    if result.supported:
        for flow in result.flows:
            identifier(flow.package_id)
    return {**response, "pattern": "decomposition"}
