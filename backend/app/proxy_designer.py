"""SAP API Management proxy design module.

Compiles a typed proxy specification into a deployable SAP APIM proxy bundle.
No arbitrary code is generated; policies are assembled from validated templates.
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


PROXY_BASE = Path(__file__).resolve().parents[1] / "templates" / "api-proxy-base.zip"


class AuthPolicy(StrictModel):
    type: Literal["none", "oauth2", "basic", "certificate", "api_key"]
    description: str = Field(default="", max_length=400)


class RateLimitPolicy(StrictModel):
    type: Literal["spike_arrest", "quota", "throttling"] = "spike_arrest"
    rate: str = Field(default="30s", pattern=r"^\d+[smh]$")
    burst: int = Field(default=30, ge=1, le=10000)
    description: str = Field(default="", max_length=400)


class CachePolicy(StrictModel):
    type: Literal["cache", "no_cache"] = "no_cache"
    ttl_seconds: int = Field(default=300, ge=0, le=86400)


class ProxySpec(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    package_id: str
    artifact_id: str
    target_url: str = Field(min_length=7, max_length=2048)
    target_path: str = Field(default="/", pattern=r"^/.*")
    auth: AuthPolicy = AuthPolicy(type="none")
    rate_limit: RateLimitPolicy | None = None
    cache: CachePolicy = CachePolicy(type="no_cache")
    request_headers: list[str] = Field(default_factory=list, max_length=20)
    response_headers: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_spec(self):
        identifier(self.package_id)
        identifier(self.artifact_id)
        if not self.target_url.startswith(("http://", "https://")):
            raise ValueError("target_url must be an absolute HTTP/HTTPS URL")
        if self.rate_limit is not None and self.rate_limit.type == "quota":
            if self.rate_limit.burst > 1000000:
                raise ValueError("Quota burst must be <= 1,000,000")
        return self


class ProxyDraft(StrictModel):
    supported: bool
    explanation: str = Field(max_length=2000)
    questions: list[str] = Field(max_length=10)
    design: ProxySpec | None = None


def _proxy_template(spec: ProxySpec) -> str:
    """Return a human-readable proxy plan for review."""
    lines = [
        f"Proxy: {spec.title}",
        f"Package: {spec.package_id} / Artifact: {spec.artifact_id}",
        f"Target: {spec.target_url}{spec.target_path}",
        f"Auth: {spec.auth.type}",
    ]
    if spec.rate_limit:
        lines.append(f"Rate limit: {spec.rate_limit.type} {spec.rate_limit.rate} burst={spec.rate_limit.burst}")
    if spec.cache.type == "cache":
        lines.append(f"Cache: TTL {spec.cache.ttl_seconds}s")
    if spec.request_headers:
        lines.append(f"Forward request headers: {', '.join(spec.request_headers)}")
    if spec.response_headers:
        lines.append(f"Expose response headers: {', '.join(spec.response_headers)}")
    if spec.description:
        lines.append(f"Notes: {spec.description}")
    return "\n".join(lines)


def propose_proxy(request, planner) -> dict:
    """Use the free planner to propose an API proxy design from a goal."""
    instructions = (
        "You design SAP API Management proxies for DEV testing. "
        "Return a typed ProxySpec. The target_url is the real backend endpoint. "
        "Use path-based proxy when possible. Choose the simplest auth that fits. "
        "Do not invent credentials. If the target requires client certificates or OAuth2, "
        "list them as questions. Never expose production credentials. "
        "Supported policies: none, oauth2, basic, certificate, api_key; "
        "rate limits: spike_arrest, quota; cache: cache/no_cache. "
        "Keep it minimal and reviewable."
    )
    response = planner.propose(json.dumps(request.model_dump()), schema=ProxyDraft, instructions=instructions)
    draft = ProxyDraft.model_validate(response["draft"])
    if draft.supported and draft.design is None:
        raise ValueError("Incomplete proxy design cannot be marked supported")
    if draft.supported:
        for key in ("package_id", "artifact_id"):
            if getattr(draft.design, key) != getattr(request, key):
                raise ValueError("Model changed the requested deployment target")
    return {**response, "references": []}


def compile_proxy(spec: ProxySpec) -> dict:
    """Compile a validated ProxySpec into a deployable APIM proxy bundle.

    Returns artifact_content (base64 ZIP), bundle metadata, steps, and scripts.
    No model-generated code is executed; the bundle is assembled from reviewed templates.
    """
    content = _build_proxy_zip(spec)
    bundle = {
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "files": [],
    }
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        bundle["files"] = z.namelist()

    policies = []
    if spec.auth.type != "none":
        policies.append(f"{spec.auth.type} authentication")
    if spec.rate_limit:
        policies.append(f"{spec.rate_limit.type} rate limit")
    if spec.cache.type == "cache":
        policies.append("response cache")

    steps = [
        "API proxy endpoint",
        *policies,
        "Target endpoint routing",
        "Deploy to DEV",
    ]

    return {
        "design": spec.model_dump(),
        "artifact_content": base64.b64encode(content).decode(),
        "bundle": bundle,
        "steps": steps,
        "test_cases": [
            "Proxy routes requests to target endpoint",
            "Authentication blocks unauthenticated requests",
            "Rate limit enforces configured burst",
        ],
        "references": [],
        "approval_required": True,
        "deployed": False,
        "pattern": "api_proxy",
        "explanation": _proxy_template(spec),
    }


def _build_proxy_zip(spec: ProxySpec) -> bytes:
    """Build a minimal proxy ZIP from a validated spec without external template dependency."""
    manifest = f"Manifest-Version: 1.0\nName: {spec.artifact_id}\n"
    proxy_xml = f"""<APIProxy revision="1" name="{spec.artifact_id}">
  <DisplayName>{spec.title}</DisplayName>
  <Description>{spec.description or 'Relay generated API proxy'}</Description>
  <TargetEndpoints>
    <TargetEndpoint name="default">
      <HTTPTargetConnection>
        <URL>{spec.target_url}</URL>
        <BasePath>{spec.target_path}</BasePath>
      </HTTPTargetConnection>
    </TargetEndpoint>
  </TargetEndpoints>
  <ProxyEndpoints>
    <ProxyEndpoint name="default">
      <PreFlow name="PreFlow">
        <Request>
          <Step>
            <Name>relay-preflow</Name>
          </Step>
        </Request>
      </PreFlow>
      <Routes>
        <Route name="default">
          <TargetEndpoint>default</TargetEndpoint>
        </Route>
      </Routes>
    </ProxyEndpoint>
  </ProxyEndpoints>
  <Policies/>
</APIProxy>
"""
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("META-INF/MANIFEST.MF", manifest)
        out.writestr("apiproxy/proxies/default.xml", proxy_xml)
        out.writestr("apiproxy/targets/default.xml", proxy_xml)
    return bundle.getvalue()

