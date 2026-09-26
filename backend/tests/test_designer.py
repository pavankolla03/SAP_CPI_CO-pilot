import base64
import io
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest

from app.designer import DesignSpec, CompileRequest, compile_design, simulate, ScenarioRequest
from app.order_designer import OrderDesignSpec, compile_orders, propose_orders
from app.pipeline_designer import PipelineDesign, compile_pipeline, propose_pipeline, simulate_pipeline


def order_spec(**kwargs):
    return OrderDesignSpec(
        package_id="Sandbox", artifact_id="OrderBatch", endpoint_path="/relay/orders", **kwargs
    )


def test_order_bundle_has_connected_native_steps_and_safe_local_ends():
    result = compile_orders(order_spec())
    with ZipFile(io.BytesIO(base64.b64decode(result["artifact_content"]))) as z:
        root = ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".iflw"))))
        b = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
        nodes = {e.get("id"): e for e in root.iter() if e.get("id")}
        assert len(root.findall(".//" + b + "subProcess")) == 2
        assert nodes["ExclusiveGateway_OrderRouter"].get("default") == "SequenceFlow_RouteAccepted"
        assert nodes["CallActivity_SplitOrders"].find(".//value[.='/orders/order']") is not None
        for e in root.iter():
            for key in ("sourceRef", "targetRef", "processRef", "bpmnElement"):
                if e.get(key):
                    assert e.get(key) in nodes
        for status in ("ACCEPTED", "REVIEW", "REJECTED"):
            assert nodes["EndEvent_" + status + "End"].find(b + "messageEventDefinition") is None
        for e in root.findall(".//" + b + "sequenceFlow"):
            assert e.get("id") in [n.text for n in nodes[e.get("sourceRef")].findall(b + "outgoing")]
            assert e.get("id") in [n.text for n in nodes[e.get("targetRef")].findall(b + "incoming")]
        assert len([n for n in z.namelist() if n.endswith(".groovy")]) == 8
    assert result["deployed"] is False
    assert result["approval_required"] is True


@pytest.mark.parametrize(
    "fields", [{"review_threshold": 0}, {"max_orders": 101}, {"arbitrary_script": "evil"}]
)
def test_order_schema_bounds(fields):
    with pytest.raises(ValueError):
        order_spec(**fields)


def test_model_cannot_retarget_or_add_code():
    request = ScenarioRequest(
        scenario="Process order batches with router",
        package_id="Sandbox",
        artifact_id="OrderBatch",
        endpoint_path="/relay/orders",
    )

    class Fake:
        def propose(self, *args, **kwargs):
            return {
                "draft": {
                    "supported": True,
                    "explanation": "ok",
                    "questions": [],
                    "design": {**order_spec().model_dump(), "artifact_id": "Other"},
                }
            }

    with pytest.raises(ValueError, match="deployment target"):
        propose_orders(request, Fake())


def test_unsupported_scenario_remains_unsupported():
    request = ScenarioRequest(
        scenario="Write sales orders into external ERP",
        package_id="Sandbox",
        artifact_id="OrderBatch",
        endpoint_path="/relay/orders",
    )

    class Fake:
        def propose(self, *args, **kwargs):
            return {
                "draft": {
                    "supported": False,
                    "explanation": "External ERP receiver not supported",
                    "questions": ["Which receiver?"],
                    "design": None,
                }
            }

    assert propose_orders(request, Fake())["draft"]["supported"] is False


def test_mapping_compiler_rejects_mismatched_expected_output_and_non_scalars():
    spec = DesignSpec(
        title="Name",
        package_id="Sandbox",
        artifact_id="Map",
        endpoint_path="/relay/map",
        required_fields=["customer.name"],
        mappings=[{"source": "customer.name", "target": "name", "transform": "uppercase"}],
    )
    assert simulate(spec, {"customer": {"name": "Ada"}}) == {"name": "ADA"}
    with pytest.raises(ValueError, match="required field"):
        simulate(spec, {"customer": {"name": []}})
    with pytest.raises(ValueError, match="expected sample"):
        compile_design(
            CompileRequest(
                design=spec, sample_input={"customer": {"name": "Ada"}}, expected_output={"name": "wrong"}
            )
        )
    assert compile_design(CompileRequest(design=spec))["deployed"] is False


def test_compile_requires_operator_and_has_no_tenant_writes(client):
    from test_agent import VIEWER

    body = order_spec().model_dump()
    initial = client.get("/v1/runs").json()
    response = client.post("/v1/designs/orders/compile", json=body)
    assert response.status_code == 200
    assert client.get("/v1/runs").json() == initial
    client.headers["Authorization"] = "Bearer " + VIEWER
    assert client.post("/v1/designs/orders/compile", json=body).status_code == 403
    client.headers.clear()
    assert client.post("/v1/designs/orders/compile", json=body).status_code == 401


def test_general_pipeline_normalizes_single_object():
    spec = PipelineDesign(
        title="Normalize employee",
        package_id="Sandbox",
        artifact_id="EmployeeNormalize",
        endpoint_path="/relay/employees/normalize",
        required_fields=["employee.id", "employee.name", "employee.email"],
        mappings=[
            {"source": "employee.id", "target": "employeeId"},
            {"source": "employee.name", "target": "displayName", "transform": "uppercase"},
            {"source": "employee.email", "target": "email", "transform": "lowercase"},
        ],
    )
    assert simulate_pipeline(
        spec, {"employee": {"id": "E-7", "name": "Ada Lovelace", "email": "ADA@EXAMPLE.COM"}}
    ) == {"employeeId": "E-7", "displayName": "ADA LOVELACE", "email": "ada@example.com"}


def test_general_pipeline_collection_deduplicates_calculates_and_routes():
    spec = PipelineDesign(
        title="Process invoices",
        package_id="Sandbox",
        artifact_id="InvoiceProcess",
        endpoint_path="/relay/invoices/process",
        collection_path="invoices",
        required_fields=["id", "quantity", "unitPrice"],
        mappings=[{"source": "id", "target": "invoiceId"}],
        calculations=[{"target": "total", "left": "quantity", "operator": "multiply", "right_field": "unitPrice"}],
        routes=[{"condition": {"source": "total", "operator": "gt", "value": 5000}, "label": "MANUAL_REVIEW"}],
        default_route="APPROVED",
        deduplicate_by="id",
        output_collection="invoices",
    )
    result = simulate_pipeline(
        spec,
        {"invoices": [
            {"id": "I-1", "quantity": 2, "unitPrice": 100},
            {"id": "I-2", "quantity": 10, "unitPrice": 600},
            {"id": "I-1", "quantity": 99, "unitPrice": 99},
        ]},
    )
    assert result == {"invoices": [
        {"invoiceId": "I-1", "total": 200.0, "status": "APPROVED"},
        {"invoiceId": "I-2", "total": 6000.0, "status": "MANUAL_REVIEW"},
    ], "count": 2}


def test_general_pipeline_filters_and_sorts_calculated_results():
    spec = PipelineDesign(
        title="Inventory alerts",
        package_id="Sandbox",
        artifact_id="InventoryAlerts",
        endpoint_path="/relay/inventory/alerts",
        collection_path="items",
        required_fields=["sku", "available", "reorderLevel"],
        mappings=[{"source": "sku", "target": "productCode", "transform": "uppercase"}],
        calculations=[{"target": "shortage", "left": "reorderLevel", "operator": "subtract", "right_field": "available"}],
        filters=[{"source": "shortage", "operator": "gt", "value": 0}],
        sort_by="shortage",
        sort_descending=True,
        output_collection="alerts",
    )
    result = simulate_pipeline(spec, {"items": [
        {"sku": "a", "available": 8, "reorderLevel": 10},
        {"sku": "b", "available": 3, "reorderLevel": 10},
        {"sku": "c", "available": 20, "reorderLevel": 10},
    ]})
    assert result == {"alerts": [
        {"productCode": "B", "shortage": 7.0},
        {"productCode": "A", "shortage": 2.0},
    ], "count": 2}


def test_general_pipeline_compiles_deployable_bundle_without_model_code():
    spec = PipelineDesign(
        title="Route tickets",
        package_id="Sandbox",
        artifact_id="TicketRoute",
        endpoint_path="/relay/tickets/route",
        collection_path="tickets",
        required_fields=["id", "priority"],
        mappings=[{"source": "id", "target": "ticketId"}],
        routes=[{"condition": {"source": "priority", "operator": "eq", "value": "high"}, "label": "URGENT"}],
        default_route="NORMAL",
    )
    result = compile_pipeline(spec)
    assert result["approval_required"] is True
    assert result["configuration_required"] is False
    with ZipFile(io.BytesIO(base64.b64decode(result["artifact_content"]))) as bundle:
        names = bundle.namelist()
        assert any(name.endswith("TicketRoute.iflw") for name in names)
        script = bundle.read(next(name for name in names if name.endswith(".groovy"))).decode()
        assert "JsonSlurper" in script
        assert "Route tickets" not in script


def test_general_pipeline_rejects_external_adapter_and_retargeting():
    request = ScenarioRequest(
        scenario="Read a file from SFTP and write it to S4",
        package_id="Sandbox",
        artifact_id="ExternalFlow",
        endpoint_path="/relay/external",
    )

    class Unsupported:
        def propose(self, *args, **kwargs):
            return {"draft": {"supported": False, "explanation": "Adapter configuration required", "questions": ["What SFTP host and S4 API?"], "design": None}}

    assert propose_pipeline(request, Unsupported())["draft"]["supported"] is False

    class Retargeted:
        def propose(self, *args, **kwargs):
            return {"draft": {"supported": True, "explanation": "bad", "questions": [], "design": {
                "title": "Bad", "package_id": "Other", "artifact_id": "ExternalFlow", "endpoint_path": "/relay/external",
                "required_fields": ["id"], "mappings": [{"source": "id", "target": "id"}],
            }}}

    with pytest.raises(ValueError, match="deployment target"):
        propose_pipeline(request, Retargeted())
