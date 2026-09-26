"""Live acceptance for the description-driven general pipeline compiler."""

import json
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.config import Settings, credential
from app.pipeline_designer import PipelineDesign, simulate_pipeline


def main():
    load_dotenv(".env")
    settings = Settings()
    token = next(
        value
        for value, principal in settings.principals().items()
        if principal.tenant_id == "sap-dev" and principal.role == "approver"
    )
    api = httpx.Client(
        base_url="http://127.0.0.1:8000",
        headers={"Authorization": "Bearer " + token},
        timeout=180,
    )
    cases = [
        {
            "name": "invoice-processing",
            "description": (
                "Receive HTTPS JSON with an invoices array. Require id, quantity and unitPrice for every invoice. "
                "Remove duplicate invoices by id. Map id to invoiceId. Calculate total as quantity multiplied by "
                "unitPrice. Route total greater than 5000 to MANUAL_REVIEW and all others to APPROVED. Return the "
                "results in an invoices array."
            ),
            "input": {
                "invoices": [
                    {"id": "INV-1", "quantity": 2, "unitPrice": 100},
                    {"id": "INV-2", "quantity": 10, "unitPrice": 600},
                    {"id": "INV-1", "quantity": 8, "unitPrice": 900},
                ]
            },
            "check": lambda value: value["count"] == 2
            and [row["status"] for row in value["invoices"]] == ["APPROVED", "MANUAL_REVIEW"],
        },
        {
            "name": "inventory-alerts",
            "description": (
                "Receive HTTPS JSON with an items array. Require sku, available and reorderLevel. Map sku to "
                "productCode in uppercase. Calculate shortage as reorderLevel minus available. Keep records whose "
                "shortage is greater than 0, sort by shortage descending and return them in an alerts array."
            ),
            "input": {
                "items": [
                    {"sku": "a-1", "available": 8, "reorderLevel": 10},
                    {"sku": "b-2", "available": 3, "reorderLevel": 10},
                    {"sku": "c-3", "available": 20, "reorderLevel": 10},
                ]
            },
            "check": lambda value: value["count"] == 2
            and [row["productCode"] for row in value["alerts"]] == ["B-2", "A-1"],
        },
        {
            "name": "employee-normalization",
            "description": (
                "Receive one HTTPS JSON employee object. Require employee.id, employee.name and employee.email. "
                "Map employee.id to employeeId, employee.name to displayName in uppercase and employee.email to "
                "email in lowercase. Return the normalized object."
            ),
            "input": {"employee": {"id": "E-7", "name": "Ada Lovelace", "email": "ADA@EXAMPLE.COM"}},
            "check": lambda value: value
            == {"employeeId": "E-7", "displayName": "ADA LOVELACE", "email": "ada@example.com"},
        },
    ]
    evidence = {"package_id": "RelayTest", "compiler": "native-bpmn-pipeline", "scenarios": []}
    for case in cases:
        response = api.post(
            "/v1/scenarios/compile",
            json={"description": case["description"], "package_id": "RelayTest", "pattern": "auto"},
        )
        response.raise_for_status()
        proposal = response.json()
        if not proposal["supported"]:
            raise RuntimeError(case["name"] + ": " + proposal["explanation"])
        spec = PipelineDesign.model_validate(proposal["design"])
        expected = simulate_pipeline(spec, case["input"])
        if not case["check"](expected):
            raise RuntimeError(case["name"] + " did not match the requested business behavior: " + json.dumps(expected))
        run = proposal["run"]
        Path('data/native-proposal-' + case['name'] + '.json').write_text(json.dumps(proposal))
        approved = api.post(
            f"/v1/runs/{run['id']}/decision",
            json={"approve": True, "plan_hash": run["plan_hash"]},
        )
        approved.raise_for_status()
        if approved.json()["status"] != "succeeded":
            raise RuntimeError(case["name"] + " deployment failed")
        case["proposal"] = proposal
        case["expected"] = expected

    unsupported = api.post(
        "/v1/scenarios/compile",
        json={
            "description": "Poll an SFTP server, decrypt PGP files and create sales orders in S4 using OData.",
            "package_id": "RelayTest",
            "pattern": "auto",
        },
    )
    unsupported.raise_for_status()
    if unsupported.json()["supported"]:
        raise RuntimeError("External-adapter scenario was incorrectly presented as deployable")

    tenant = settings.tenants()["sap-dev"]
    oauth = httpx.post(
        tenant.token_url,
        auth=(credential("SAP_RUNTIME_CLIENT_ID"), credential("SAP_RUNTIME_CLIENT_SECRET")),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    oauth.raise_for_status()
    runtime_headers = {"Authorization": "Bearer " + oauth.json()["access_token"]}
    runtime_base = tenant.api_url.removesuffix("/api/v1").replace("-cpitrial06.", "-cpitrial06-rt.")
    for case in cases:
        design = case["proposal"]["design"]
        response = httpx.post(
            runtime_base + "/http" + design["endpoint_path"],
            headers=runtime_headers,
            json=case["input"],
            timeout=60,
        )
        response.raise_for_status()
        actual = response.json()
        if actual != case["expected"]:
            raise RuntimeError(case["name"] + " runtime mismatch: " + json.dumps(actual))
        evidence["scenarios"].append(
            {
                "name": case["name"],
                "artifact_id": design["artifact_id"],
                "endpoint_path": design["endpoint_path"],
                "design": design,
                "model": case["proposal"].get("model"),
                "key_slots": case["proposal"].get("key_slots", []),
                "http_status": response.status_code,
                "input": case["input"],
                "output": actual,
            }
        )
        print(case["name"], design["artifact_id"], response.status_code, json.dumps(actual), flush=True)
    evidence["external_adapter_guard"] = {
        "supported": unsupported.json()["supported"],
        "explanation": unsupported.json()["explanation"],
        "questions": unsupported.json()["questions"],
    }
    Path("data/native-bpmn-acceptance.json").write_text(json.dumps(evidence, indent=2) + "\n")
    Path("docs/native-bpmn-acceptance.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print("PASS", len(cases), "live scenarios and external-adapter guard", flush=True)


if __name__ == "__main__":
    main()
