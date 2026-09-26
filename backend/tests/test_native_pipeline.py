import base64
import io
import xml.etree.ElementTree as E
from zipfile import ZipFile
import pytest
from app.pipeline_designer import PipelineDesign, compile_pipeline, simulate_pipeline

B = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"


def spec(**changes):
    return PipelineDesign.model_validate(
        dict(
            title="Test",
            package_id="Sandbox",
            artifact_id="NativeTest",
            endpoint_path="/relay/native",
            required_fields=["id"],
            **changes,
        )
    )


def test_topology_follows_operations_and_preview_matches_zip():
    simple = compile_pipeline(spec(mappings=[dict(source="id", target="identifier")]))
    batch = compile_pipeline(
        spec(
            collection_path="records",
            calculations=[dict(target="double", left="id", operator="multiply", right_value=2)],
            routes=[dict(condition=dict(source="double", operator="gt", value=10), label="HIGH")],
            default_route="LOW",
        )
    )
    a, b = E.fromstring(simple["bpmn_xml"]), E.fromstring(batch["bpmn_xml"])
    assert not a.findall(".//" + B + "exclusiveGateway")
    assert len(b.findall(".//" + B + "exclusiveGateway")) == 1
    assert len(b.findall(B + "process")) == 2
    assert len(a.findall(B + "process")) == 1
    assert "General Splitter" not in simple["bpmn_xml"]
    assert "General Splitter" in batch["bpmn_xml"]
    assert "Calculate double" in batch["bpmn_xml"]
    for result in [simple, batch]:
        with ZipFile(io.BytesIO(base64.b64decode(result["artifact_content"]))) as z:
            assert z.read(next(n for n in z.namelist() if n.endswith(".iflw"))).decode() == result["bpmn_xml"]
        root = E.fromstring(result["bpmn_xml"])
        ids = {e.get("id"): e for e in root.iter() if e.get("id")}
        assert len(root.findall(".//" + B + "subProcess")) == 1
        for e in root.iter():
            for attr in ["sourceRef", "targetRef", "processRef", "bpmnElement", "default"]:
                if e.get(attr):
                    assert e.get(attr) in ids
        for edge in root.findall(".//" + B + "sequenceFlow"):
            assert edge.get("id") in [n.text for n in ids[edge.get("sourceRef")].findall(B + "outgoing")]
            assert edge.get("id") in [n.text for n in ids[edge.get("targetRef")].findall(B + "incoming")]


def test_acceptance_mismatch_rejected_and_zero_multiplication_works():
    design = spec(calculations=[dict(target="total", left="id", operator="multiply", right_value=0)])
    assert simulate_pipeline(design, {"id": 7}) == {"total": 0}
    with pytest.raises(ValueError, match="expected sample"):
        compile_pipeline(design, {"id": 7}, {"total": 14})


def test_simulation_does_not_mutate_nested_input():
    design = spec(mappings=[dict(source="nested.name", target="nested.name", transform="uppercase")])
    payload = {"id": 1, "nested": {"name": "Ada"}}
    assert simulate_pipeline(design, payload) == {"nested": {"name": "ADA"}}
    assert payload["nested"]["name"] == "Ada"


def test_multistep_calculation_projects_only_final_fields():
    design = spec(calculations=[dict(target='scaled',left='id',operator='multiply',right_value=1.8),dict(target='fahrenheit',left='scaled',operator='add',right_value=32)],output_fields=['fahrenheit'])
    result = compile_pipeline(design, {'id':10}, {'fahrenheit':50})
    assert result['sample_output'] == {'fahrenheit':50}
    assert 'Calculate scaled' in result['bpmn_xml'] and 'Calculate fahrenheit' in result['bpmn_xml']


def test_research_failure_is_explicit(monkeypatch):
    import httpx
    from app import research

    research._retrieve.cache_clear()

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(research.httpx, "stream", unavailable)
    rows = research.research_references("router")
    assert all(r["status"] == "unavailable" for r in rows[-2:])
    research._retrieve.cache_clear()
