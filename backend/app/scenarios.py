"""Description-first compilation into a reviewed, typed iFlow pipeline."""

from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from .designer import ScenarioRequest
from .models import RunRequest, identifier
from .order_designer import OrderDesignSpec, compile_orders, propose_orders
from .pipeline_designer import PipelineDesign, compile_pipeline, propose_pipeline, simulate_pipeline


class DescriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=10, max_length=2000)
    package_id: str = Field(default="", max_length=160)
    pattern: Literal["auto", "json_pipeline", "batch_orders", "json_transform"] = "auto"
    clarifications: str = Field(default="", max_length=4000)
    sample_input: dict | None = None
    expected_output: dict | None = None


def describe(body, principal, agent, planner):
    tenant = agent.tenants[principal.tenant_id]
    package = body.package_id or tenant.description_package_id
    if not package:
        raise ValueError("Select an existing package, or configure the tenant description_package_id")
    identifier(package)
    agent.clients[principal.tenant_id].package(package)
    suffix = uuid4().hex[:12]
    target = ScenarioRequest(
        scenario=body.description,
        package_id=package,
        artifact_id="RelayFlow" + suffix,
        endpoint_path="/relay/flows/" + suffix,
        sample_input=body.sample_input,
        expected_output=body.expected_output,
    )
    proposed = propose_pipeline(target, planner)
    slots = [proposed['key_slot']] if 'key_slot' in proposed else []
    # One semantic correction can use the concrete mismatch, but never skip acceptance.
    if proposed['draft']['supported'] and body.sample_input is not None and body.expected_output is not None:
        design = PipelineDesign.model_validate(proposed['draft']['design'])
        actual = simulate_pipeline(design, body.sample_input)
        if actual != body.expected_output:
            target = target.model_copy(update={'revision_feedback': {'previous_design': design.model_dump(), 'actual_output': actual, 'expected_output': body.expected_output}})
            proposed = propose_pipeline(target, planner)
            if 'key_slot' in proposed:
                slots.append(proposed['key_slot'])
    draft = proposed["draft"]
    if not draft["supported"]:
        return {
            "supported": False,
            "pattern": "json_pipeline",
            "explanation": draft["explanation"],
            "questions": draft["questions"],
            "model": proposed.get("model"),
            "key_slots": slots,
        }
    compiled = compile_pipeline(PipelineDesign.model_validate(draft["design"]), body.sample_input, body.expected_output)
    request = RunRequest(
        goal=body.description,
        action="upload_deploy",
        package_id=package,
        artifact_id=target.artifact_id,
        name=compiled["design"]["title"],
        artifact_content=compiled["artifact_content"],
    )
    run = agent.start(request, principal)
    return {
        "supported": True,
        "pattern": "json_pipeline",
        "explanation": draft["explanation"],
        "design": compiled["design"],
        "steps": compiled["steps"],
        "scripts": compiled["scripts"],
        "bundle": compiled["bundle"],
        "bpmn_xml": compiled["bpmn_xml"],
        "artifact_content": compiled["artifact_content"],
        "references": proposed.get('references', []),
        "test_cases": compiled["test_cases"],
        "sample_input": compiled.get("sample_input"),
        "sample_output": compiled.get("sample_output"),
        "run": run,
        "model": proposed.get("model"),
        "key_slots": slots,
        "scope": "Typed description-driven HTTPS JSON pipeline. External adapters require a dedicated adapter module and connection configuration. Deployment requires review and approval.",
    }


def describe_orders(body, principal, agent, planner):
    """Compatibility endpoint: retain its original explicit order-pattern behavior."""
    tenant = agent.tenants[principal.tenant_id]
    package = body.package_id or tenant.description_package_id
    if not package:
        raise ValueError("Select an existing package, or configure the tenant description_package_id")
    identifier(package)
    agent.clients[principal.tenant_id].package(package)
    suffix = uuid4().hex[:12]
    target = ScenarioRequest(
        scenario=body.description,
        package_id=package,
        artifact_id="RelayOrders" + suffix,
        endpoint_path="/relay/orders/" + suffix,
    )
    proposed = propose_orders(target, planner)
    draft = proposed["draft"]
    if not draft["supported"]:
        return {
            "supported": False,
            "pattern": "batch_orders",
            "explanation": draft["explanation"],
            "questions": draft["questions"],
            "model": proposed.get("model"),
            "key_slots": [proposed["key_slot"]] if "key_slot" in proposed else [],
        }
    compiled = compile_orders(OrderDesignSpec.model_validate(draft["design"]))
    request = RunRequest(
        goal=body.description,
        action="upload_deploy",
        package_id=package,
        artifact_id=target.artifact_id,
        name=compiled["design"]["title"],
        artifact_content=compiled["artifact_content"],
    )
    run = agent.start(request, principal)
    return {
        "supported": True,
        "pattern": "batch_orders",
        "explanation": draft["explanation"],
        "design": compiled["design"],
        "steps": compiled["steps"],
        "scripts": compiled["scripts"],
        "bundle": compiled["bundle"],
        "test_cases": compiled["test_cases"],
        "sample_input": compiled.get("sample_input"),
        "sample_output": compiled.get("sample_output"),
        "run": run,
        "model": proposed.get("model"),
        "key_slots": [proposed["key_slot"]] if "key_slot" in proposed else [],
        "scope": "Legacy batch-order endpoint. Deployment requires review and approval.",
    }
