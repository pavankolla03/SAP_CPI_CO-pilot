import base64
import io
from zipfile import ZipFile
import xml.etree.ElementTree as E
from app.messaging_designer import compile_messaging, MessagingDesign
from test_agent import plan, decide


def test_upload_only_does_not_deploy(client):
    flow = compile_messaging(MessagingDesign())["flows"][2]
    run = plan(
        client,
        action="upload",
        package_id="AgentSandbox",
        artifact_id=flow["artifact_id"],
        artifact_content=flow["artifact_content"],
    )
    assert run["plan"]["operations"] == ["upload"]
    assert client.get("/v1/iflows/" + flow["artifact_id"]).status_code == 404
    result = decide(client, run).json()
    assert result["status"] == "succeeded"
    assert client.get("/v1/iflows/" + flow["artifact_id"] + "/runtime").status_code == 404
    assert result["test"]["passed"]


def test_messaging_native_graph_and_configuration():
    flows = compile_messaging(MessagingDesign())["flows"]
    assert len(flows) == 5
    for flow in flows:
        with ZipFile(io.BytesIO(base64.b64decode(flow["artifact_content"]))) as z:
            xml = E.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".iflw"))))
            ids = {e.get("id") for e in xml.iter() if e.get("id")}
            for e in xml.iter():
                for key in ["sourceRef", "targetRef", "processRef", "bpmnElement", "default"]:
                    if e.get(key):
                        assert e.get(key) in ids
            if flow["configuration_required"]:
                assert flow["parameters"]["SolaceHost"] == "broker.invalid"
                assert flow["parameters"]["SolaceCredentialAlias"] == "RelaySolaceNotConfigured"
                assert b"connectWithTLS" in E.tostring(xml)
            if flow["artifact_id"] == "RelayJMSWorker":
                assert b"relayPark" in E.tostring(xml)
                assert b"ErrorEventSubProcessTemplate" not in E.tostring(xml)
                assert (
                    "throw new IllegalStateException"
                    in z.read("src/main/resources/script/CallActivity_Process.groovy").decode()
                )
