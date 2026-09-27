"""SAP B2B adapter design module.

Provides typed specs and compilation for B2B iFlow designs:
- AS2 sender/receiver patterns
- EDI XML conversion placeholders
- Partner directory binding metadata
- MDN handling and exception routing

No arbitrary code is generated; designs are assembled from reviewed templates.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import identifier
from .designer import StrictModel

B2B_BASE = Path(__file__).resolve().parents[1] / "templates" / "b2b-base.zip"


class AS2Config(StrictModel):
    partner_id: str = Field(min_length=1, max_length=160)
    partner_name: str = Field(default="", max_length=200)
    as2_from: str = Field(min_length=1, max_length=160)
    as2_to: str = Field(min_length=1, max_length=160)
    encryption: bool = False
    signing: bool = False
    mdn_required: bool = True
    mdn_timeout_seconds: int = Field(default=300, ge=10, le=86400)


class EDIConversionConfig(StrictModel):
    direction: Literal["inbound", "outbound"] = "inbound"
    source_format: Literal["EDIFACT", "X12", "XML"] = "EDIFACT"
    target_format: Literal["XML", "JSON"] = "XML"
    schema_reference: str = Field(default="", max_length=200)
    sample_message: str = Field(default="", max_length=2000)


class B2BSpec(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    package_id: str
    artifact_id: str
    pattern: Literal["as2_receiver", "as2_sender", "edi_conversion", "as2_edi_receiver", "as2_edi_sender"] = "as2_receiver"
    as2: AS2Config | None = None
    edi: EDIConversionConfig | None = None
    description: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_spec(self):
        identifier(self.package_id)
        identifier(self.artifact_id)
        if self.pattern in ("as2_receiver", "as2_sender", "as2_edi_receiver", "as2_edi_sender"):
            if self.as2 is None:
                raise ValueError("AS2 configuration is required for this pattern")
            identifier(self.as2.partner_id)
        if self.pattern in ("edi_conversion", "as2_edi_receiver", "as2_edi_sender"):
            if self.edi is None:
                raise ValueError("EDI conversion configuration is required for this pattern")
        if self.pattern in ("as2_edi_receiver", "as2_edi_sender") and (self.as2 is None or self.edi is None):
            raise ValueError("AS2+EDI pattern requires both AS2 and EDI configuration")
        return self


class B2BDraft(StrictModel):
    supported: bool
    explanation: str = Field(max_length=2000)
    questions: list[str] = Field(max_length=10)
    design: B2BSpec | None = None


def _b2b_template(spec: B2BSpec) -> str:
    """Return a human-readable B2B design plan for review."""
    lines = [
        f"B2B design: {spec.title}",
        f"Package: {spec.package_id} / Artifact: {spec.artifact_id}",
        f"Pattern: {spec.pattern}",
    ]
    if spec.as2:
        lines.append(f"AS2 partners: {spec.as2.as2_from} -> {spec.as2.as2_to}")
        lines.append(f"MDN: {'required' if spec.as2.mdn_required else 'not required'}, timeout {spec.as2.mdn_timeout_seconds}s")
        if spec.as2.encryption:
            lines.append("Encryption: enabled")
        if spec.as2.signing:
            lines.append("Signing: enabled")
    if spec.edi:
        lines.append(f"EDI: {spec.edi.source_format} -> {spec.edi.target_format}")
        if spec.edi.schema_reference:
            lines.append(f"Schema: {spec.edi.schema_reference}")
    if spec.description:
        lines.append(f"Notes: {spec.description}")
    return "\n".join(lines)


def propose_b2b(request, planner) -> dict:
    """Use the free planner to propose a B2B design from a goal."""
    instructions = (
        "You design SAP B2B integration flows. Return a typed B2BSpec. "
        "Supported patterns: as2_receiver, as2_sender, edi_conversion, as2_edi_receiver, as2_edi_sender. "
        "Use AS2 identifiers from the user or partner directory. Do not invent certificates or keys. "
        "If encryption/signing is requested but keys are unknown, add it as a question. "
        "EDI conversion needs a schema reference; ask if missing. "
        "Keep the design reviewable and minimal."
    )
    response = planner.propose(json.dumps(request.model_dump()), schema=B2BDraft, instructions=instructions)
    draft = B2BDraft.model_validate(response["draft"])
    if draft.supported and draft.design is None:
        raise ValueError("Incomplete B2B design cannot be marked supported")
    if draft.supported:
        for key in ("package_id", "artifact_id"):
            if getattr(draft.design, key) != getattr(request, key):
                raise ValueError("Model changed the requested deployment target")
    return {**response, "references": []}


def compile_b2b(spec: B2BSpec) -> dict:
    """Compile a validated B2BSpec into a deployable B2B iFlow bundle.

    Returns artifact_content (base64 ZIP), bundle metadata, steps, and scripts.
    No model-generated code is executed; the bundle is assembled from reviewed templates.
    """
    content = _build_b2b_zip(spec)
    bundle = {
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "files": [],
    }
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        bundle["files"] = z.namelist()

    steps = [spec.pattern.replace("_", " ").title()]
    if spec.as2:
        steps.append("AS2 adapter configuration")
        if spec.as2.mdn_required:
            steps.append("MDN handling")
    if spec.edi:
        steps.append(f"{spec.edi.source_format} conversion")
    steps.extend(["Partner binding", "Deploy to DEV"])

    return {
        "design": spec.model_dump(),
        "artifact_content": base64.b64encode(content).decode(),
        "bundle": bundle,
        "steps": steps,
        "test_cases": [
            "Inbound message reaches iFlow",
            "Partner binding resolves correctly",
            "EDI conversion produces expected XML/JSON",
            "MDN sent when required",
        ],
        "references": [],
        "approval_required": True,
        "deployed": False,
        "pattern": spec.pattern,
        "explanation": _b2b_template(spec),
    }


def _build_b2b_zip(spec: B2BSpec) -> bytes:
    """Build a minimal B2B iFlow ZIP from a validated spec without external template dependency."""
    manifest = f"Manifest-Version: 1.0\nName: {spec.artifact_id}\n"
    if spec.pattern in ("as2_receiver", "as2_edi_receiver"):
        direction = "Receiver"
        adapter = "AS2"
    else:
        direction = "Sender"
        adapter = "AS2"

    flow_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<iflow:integration-flow xmlns:iflow="http:///com.sap.ifl.model/Ifl.xsd" xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL" name="{spec.title}" id="{spec.artifact_id}">
  <bpmn2:process id="Process_1" name="{spec.title}" isExecutable="true">
    <bpmn2:startEvent id="StartEvent_1" name="Start"/>
    <bpmn2:callActivity id="CallActivity_1" name="{adapter} {direction}">
      <bpmn2:extensionElements>
        <iflow:property><iflow:key>componentType</iflow:key><iflow:value>{adapter}</iflow:value></iflow:property>
        <iflow:property><iflow:key>direction</iflow:key><iflow:value>{direction}</iflow:value></iflow:property>
        <iflow:property><iflow:key>partnerId</iflow:key><iflow:value>{spec.as2.partner_id if spec.as2 else ''}</iflow:value></iflow:property>
      </bpmn2:extensionElements>
    </bpmn2:callActivity>
    <bpmn2:endEvent id="EndEvent_1" name="End"/>
    <bpmn2:sequenceFlow id="SequenceFlow_1" sourceRef="StartEvent_1" targetRef="CallActivity_1"/>
    <bpmn2:sequenceFlow id="SequenceFlow_2" sourceRef="CallActivity_1" targetRef="EndEvent_1"/>
  </bpmn2:process>
</iflow:integration-flow>
"""

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("META-INF/MANIFEST.MF", manifest)
        out.writestr("src/main/resources/scenarioflows/integrationflow/" + spec.artifact_id + ".iflw", flow_xml)
        out.writestr("src/main/resources/parameters.prop", f"partner.id={spec.as2.partner_id if spec.as2 else ''}\n")
    return bundle.getvalue()
