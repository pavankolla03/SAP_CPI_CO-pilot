"""Expansion contract only. Future modules cannot bypass the central approval executor."""
from typing import Protocol

from pydantic import BaseModel


class CapabilityPlan(BaseModel):
    capability: str
    tenant_id: str
    operations: list[dict]
    before: dict
    after: dict
    required_scopes: list[str]
    risks: list[str]


class Capability(Protocol):
    def discover(self, tenant_id: str, target: str) -> dict: ...
    def propose(self, tenant_id: str, intent: dict, snapshot: dict) -> CapabilityPlan: ...
    def validate(self, evidence: dict) -> dict: ...
