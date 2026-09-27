"""Template library for reusable SAP integration patterns.

Provides curated templates and parameterized forms for common integration scenarios.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .designer import StrictModel
from .models import identifier


class TemplateForm(BaseModel):
    fields: list[str]
    hints: dict[str, str] = Field(default_factory=dict)


class IntegrationTemplate(StrictModel):
    id: str
    name: str
    category: Literal["connector", "messaging", "b2b", "monitoring", "security", "processing"] = "connector"
    description: str = Field(max_length=1000)
    adapter_type: Literal["https", "soap", "odata", "sftp", "file", "jms", "solace", "as2", "processdirect", "api_proxy", "edi"] = "https"
    form: TemplateForm | None = None


@dataclass
class TemplateDefinition:
    id: str
    name: str
    category: str
    description: str
    adapter_type: str
    form: dict | None = None


TEMPLATES: list[TemplateDefinition] = [
    TemplateDefinition(
        id="https-json",
        name="HTTPS JSON",
        category="connector",
        description="Basic HTTPS request-reply with JSON payload.",
        adapter_type="https",
        form={"fields": ["target_url", "method", "timeout_ms"], "hints": {"target_url": "https://backend.example.com/api", "method": "GET, POST, PUT"}},
    ),
    TemplateDefinition(
        id="odata-read",
        name="OData READ",
        category="connector",
        description="Read data from an OData service with pagination and filtering.",
        adapter_type="odata",
        form={"fields": ["service_url", "entity_set", "select", "filter"], "hints": {"service_url": "https://s4hana.example.com/sap/opu/odata"}},
    ),
    TemplateDefinition(
        id="as2-receiver",
        name="AS2 Receiver",
        category="b2b",
        description="Receive an EDI or XML payload over AS2 with optional MDN.",
        adapter_type="as2",
        form={"fields": ["partner_id", "as2_from", "as2_to", "mdn_required"], "hints": {"partner_id": "Partner directory parameter"}},
    ),
    TemplateDefinition(
        id="edi-conversion",
        name="EDI Conversion",
        category="b2b",
        description="Convert EDIFACT or X12 into XML or JSON with a provided mapping.",
        adapter_type="edi",
        form={"fields": ["direction", "source_format", "target_format", "schema_reference"], "hints": {"schema_reference": "Mapping or XSLT resource"}},
    ),
    TemplateDefinition(
        id="jms-retry",
        name="JMS Retry Pattern",
        category="messaging",
        description="Send or receive JMS messages with retry, backoff, and dead-letter routing.",
        adapter_type="jms",
        form={"fields": ["jms_provider", "queue_name", "retries", "backoff_seconds"], "hints": {"jms_provider": "SAP JMS or Solace"}},
    ),
    TemplateDefinition(
        id="api-proxy",
        name="API Proxy",
        category="security",
        description="Wrap an existing API endpoint with authentication and rate limiting.",
        adapter_type="api_proxy",
        form={"fields": ["target_url", "auth_type", "rate_limit"], "hints": {"auth_type": "none, oauth2, basic, api_key"}},
    ),
    TemplateDefinition(
        id="processdirect",
        name="ProcessDirect Router",
        category="messaging",
        description="Route messages between local integration flows without network hops.",
        adapter_type="processdirect",
        form={"fields": ["target_flow", "queue_name"], "hints": {"target_flow": "Target artifact ID"}},
    ),
    TemplateDefinition(
        id="sftp-pickup",
        name="SFTP File Pickup",
        category="connector",
        description="Poll SFTP, transfer files, and archive or delete after processing.",
        adapter_type="sftp",
        form={"fields": ["sftp_host", "directory", "filename_pattern", "archive_dir"], "hints": {"filename_pattern": "*.xml or .*"}},
    ),
    TemplateDefinition(
        id="messaging-solace",
        name="Solace Event Layer",
        category="messaging",
        description="Publish/consume events on Solace with guaranteed delivery.",
        adapter_type="solace",
        form={"fields": ["message_vpn", "topic", "queue"], "hints": {"message_vpn": "Solace VPN name"}},
    ),
    TemplateDefinition(
        id="monitoring-mpl",
        name="MPL Monitoring",
        category="monitoring",
        description="Read message processing logs for an iFlow to verify delivery and failures.",
        adapter_type="https",
        form={"fields": ["artifact_id", "time_range_minutes"], "hints": {"time_range_minutes": "Last 60 minutes"}},
    ),
]


def list_templates() -> list[dict]:
    return [IntegrationTemplate(
        id=t.id,
        name=t.name,
        category=t.category,
        description=t.description,
        adapter_type=t.adapter_type,
        form=TemplateForm(fields=t.form["fields"], hints=t.form["hints"]) if t.form else None,
    ).model_dump() for t in TEMPLATES]


def get_template(template_id: str) -> dict | None:
    for template in TEMPLATES:
        if template.id == template_id:
            return IntegrationTemplate(
                id=template.id,
                name=template.name,
                category=template.category,
                description=template.description,
                adapter_type=template.adapter_type,
                form=TemplateForm(fields=template.form["fields"], hints=template.form["hints"]) if template.form else None,
            ).model_dump()
    return None


def template_catalog() -> dict:
    return {
        "templates": list_templates(),
        "categories": ["connector", "messaging", "b2b", "monitoring", "security", "processing"],
        "count": len(TEMPLATES),
    }
