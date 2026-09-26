"""Native JMS retry and layered Solace AMQP designs. Broker delivery needs live tests."""

import base64
import copy
import io
import xml.etree.ElementTree as E
from zipfile import ZipFile, ZIP_DEFLATED
from pydantic import Field
from .order_designer import BASE, B, IFL, NS, props
from .designer import StrictModel
from .models import inspect_bundle


class MessagingDesign(StrictModel):
    retry_limit: int = Field(default=3, ge=1, le=5)
    retry_interval_minutes: int = Field(default=1, ge=1, le=60)


IMPORTS = "import com.sap.gateway.ip.core.customdev.util.Message\nimport groovy.json.JsonSlurper\nimport groovy.json.JsonOutput\n"
INGRESS = (
    IMPORTS
    + """Message processData(Message message) {
    def body = new JsonSlurper().parseText(message.getBody(String))
    if (!(body instanceof Map) || !(body.id instanceof String) || !(body.id ==~ /[A-Za-z0-9_-]{1,64}/)) throw new IllegalArgumentException('Invalid event ID')
    if (!(body.payload instanceof Map)) throw new IllegalArgumentException('payload must be an object')
    def failures = body.failUntilRetry ?: 0
    if (!(failures instanceof Number) || failures < 0 || failures > 3 || failures != failures.intValue()) throw new IllegalArgumentException('failUntilRetry must be 0..3 for DEV testing')
    message.setHeader('SAP_ApplicationID', body.id)
    message.setBody(JsonOutput.toJson([id:body.id, type:'relay.order.requested.v1', payload:body.payload, failUntilRetry:failures]))
    return message
}
"""
)
WORKER = (
    IMPORTS
    + """Message processData(Message message) {
    def body = new JsonSlurper().parseText(message.getBody(String))
    int retries = (message.getHeader('SAPJMSRetries', Object) ?: 0) as int
    if (retries < ((body.failUntilRetry ?: 0) as int)) throw new IllegalStateException('Synthetic DEV transient failure')
    if (!(body.payload instanceof Map)) throw new IllegalArgumentException('Invalid payload')
    message.setHeader('SAP_ApplicationID', body.id)
    def log = messageLogFactory.getMessageLog(message)
    if (log != null) { log.addCustomHeaderProperty('RelayEventId', body.id); log.addCustomHeaderProperty('RelayRetryCount', retries.toString()); log.addCustomHeaderProperty('RelayOutcome', 'PROCESSED') }
    message.setBody(JsonOutput.toJson([id:body.id, status:'PROCESSED', retries:retries, payload:body.payload]))
    return message
}
"""
)
PARK = (
    IMPORTS
    + """Message processData(Message message) {
    def id = 'unparseable'
    try {
        def body = new JsonSlurper().parseText(message.getBody(String))
        if (body instanceof Map && body.id instanceof String && body.id ==~ /[A-Za-z0-9_-]{1,64}/) id = body.id
    } catch (Exception ignored) { }
    def log = messageLogFactory.getMessageLog(message)
    if (log != null) { log.addCustomHeaderProperty('RelayEventId', id); log.addCustomHeaderProperty('RelayOutcome', 'PARKED') }
    message.setHeader('SAP_ApplicationID', id)
    return message
}
"""
)
ACK = (
    IMPORTS
    + """Message processData(Message message) {
    def body = new JsonSlurper().parseText(message.getBody(String))
    message.setHeader('CamelHttpResponseCode', 202)
    message.setHeader('Content-Type', 'application/json')
    message.setBody(JsonOutput.toJson([id:body.id,status:'QUEUED']))
    return message
}
"""
)
NORMALIZE = (
    IMPORTS
    + """Message processData(Message message) {
    def event = new JsonSlurper().parseText(message.getBody(String))
    if (event.type != 'relay.order.requested.v1' || !(event.payload instanceof Map)) throw new IllegalArgumentException('Unsupported event contract')
    def order = event.payload
    if (!(order.amount instanceof Number) || !(order.quantity instanceof Number) || order.amount < 0 || order.quantity <= 0) throw new IllegalArgumentException('Invalid order values')
    message.setHeader('SAP_ApplicationID', event.id)
    message.setBody(JsonOutput.toJson([id:event.id, type:'relay.order.validated.v1', payload:[orderId:event.id,total:order.amount*order.quantity]]))
    return message
}
"""
)
PROJECT = (
    IMPORTS
    + """Message processData(Message message) {
    def event = new JsonSlurper().parseText(message.getBody(String))
    if (event.type != 'relay.order.validated.v1' || !(event.payload instanceof Map)) throw new IllegalArgumentException('Unsupported event contract')
    message.setHeader('SAP_ApplicationID', event.id)
    message.setBody(JsonOutput.toJson([id:event.id,type:'relay.fulfillment.requested.v1',payload:[externalOrderId:event.payload.orderId,netAmount:event.payload.total]]))
    return message
}
"""
)


class Flow:
    def __init__(self, artifact, title):
        self.artifact = artifact
        self.scripts = {}
        self.parameters = {}
        self.refs = []
        for key, value in NS.items():
            E.register_namespace(key, value)
        self.source = ZipFile(BASE / "https-json-base.zip")
        self.root = E.fromstring(
            self.source.read(next(n for n in self.source.namelist() if n.endswith(".iflw")))
        )
        self.process = self.root.find(B + "process")
        self.process.set("name", title)
        self.script_template = copy.deepcopy(self.process.find(B + "callActivity"))
        for e in list(self.process):
            if e.tag != B + "extensionElements":
                self.process.remove(e)
        self.collab = self.root.find(B + "collaboration")
        self.sender = self.collab.find(B + "messageFlow")
        self.sender.set("targetRef", "StartEvent_2")
        self.node("startEvent", "StartEvent_2", "Start", event=True)
        self.node("endEvent", "EndEvent_2", "End", event=True)
        self.coords = {"Participant_Process_1": (100, 50, 1300, 430), "Participant_1": (15, 130, 55, 80)}

    def node(self, kind, ident, name, properties=None, event=False):
        n = E.SubElement(self.process, B + kind, {"id": ident, "name": name})
        props(n, properties or {})
        if event:
            E.SubElement(n, B + "messageEventDefinition")
        return n

    def script(self, ident, title, code):
        n = copy.deepcopy(self.script_template)
        n.set("id", ident)
        n.set("name", title)
        for c in list(n):
            if c.tag != B + "extensionElements":
                n.remove(c)
        file = ident + ".groovy"
        props(n, {"script": file})
        self.process.append(n)
        self.scripts[file] = code

    def edge(self, a, b, ident=None, condition=None):
        ident = ident or "SequenceFlow_" + a + "_" + b
        e = E.SubElement(self.process, B + "sequenceFlow", {"id": ident, "sourceRef": a, "targetRef": b})
        for key, tag in [(a, "outgoing"), (b, "incoming")]:
            n = next(n for n in self.process if n.get("id") == key)
            E.SubElement(n, B + tag).text = ident
        if condition:
            props(e, {"expressionType": "NonXML"})
            E.SubElement(
                e, B + "conditionExpression", {"{" + NS["xsi"] + "}type": "bpmn2:tFormalExpression"}
            ).text = condition
        return ident

    def https(self, path):
        props(self.sender, {"urlPath": path})

    def adapter(
        self,
        kind,
        direction,
        queue=None,
        topic=None,
        channel="MessageFlow_4",
        node="StartEvent_2",
        retry=None,
    ):
        if direction == "Sender":
            e = self.sender
            for c in list(e):
                e.remove(c)
        else:
            participant = "Participant_" + channel
            n = E.SubElement(
                self.collab,
                B + "participant",
                {"id": participant, "name": channel, IFL + "type": "EndpointRecevier"},
            )
            props(n, {"ifl:type": "EndpointRecevier"})
            self.coords[participant] = (1470, 140 + len(self.coords) * 35, 65, 80)
            e = E.SubElement(
                self.collab,
                B + "messageFlow",
                {"id": channel, "name": kind, "sourceRef": node, "targetRef": participant},
            )
        e.set("name", kind)
        if kind == "JMS":
            version = "1.4.3" if direction == "Sender" else "1.6.3"
            values = {
                "ComponentType": "JMS",
                "ComponentNS": "sap",
                "componentVersion": version.rsplit(".", 1)[0],
                "Name": "JMS",
                "system": "Sender" if direction == "Sender" else channel,
                "direction": direction,
                "TransportProtocol": "Not Applicable",
                "MessageProtocol": "Not Applicable",
                "TransportProtocolVersion": version,
                "MessageProtocolVersion": version,
                "ComponentSWCVId": version,
                "ComponentSWCVName": "external",
                "cmdVariantUri": f"ctype::AdapterVariant/cname::sap:JMS/tp::Not Applicable/mp::Not Applicable/direction::{direction}/version::{version}",
            }
            if direction == "Sender":
                values.update(
                    {
                        "QueueName": queue,
                        "QueueName_inbound": queue,
                        "NumberConcurrentProcesses": "1",
                        "RetryInterval": str(retry.retry_interval_minutes),
                        "ExponentialBackoff": "false",
                        "MaxRetryInterval": "60",
                        "MaxRetries": "-1",
                        "useDeadLetterQueue": "true",
                    }
                )
            else:
                values.update(
                    {
                        "QueueName_outbound": queue,
                        "UseMessageCompression": "false",
                        "EncryptMessage": "true",
                        "RetentionThresholdAlerting": "2",
                        "ExpirationPeriod": "7",
                    }
                )
            props(e, values)
        else:
            template = E.parse(BASE / "patterns" / ("amqp-" + direction.lower() + ".xml")).getroot()
            values = {
                x.findtext("key"): x.findtext("value") or ""
                for x in template.findall(".//" + IFL + "property")
            }
            values.update(
                {
                    "host": "{{SolaceHost}}",
                    "port": "{{SolacePort}}",
                    "credentialName": "{{SolaceCredentialAlias}}",
                    "system": "Sender" if direction == "Sender" else channel,
                    "connectWithTLS": "true",
                    "destinationName": "{{"
                    + ("InputQueue" if direction == "Sender" else "OutputTopic")
                    + "}}",
                }
            )
            if direction == "Receiver":
                values.update({"destinationType": "topic", "delivery": "persistent"})
            props(e, values)
            settings = {
                "SolaceHost": ("broker.invalid", "host"),
                "SolacePort": ("5671", "port"),
                "SolaceCredentialAlias": ("RelaySolaceNotConfigured", "credentialName"),
                ("InputQueue" if direction == "Sender" else "OutputTopic"): (
                    queue if direction == "Sender" else topic,
                    "destinationName",
                ),
            }
            for param, (default, attribute) in settings.items():
                self.parameters[param] = default
                self.refs.append(
                    {
                        "attribute_category": "Sender" if direction == "Sender" else channel,
                        "attribute_id": values["cmdVariantUri"] + "/attrId::" + attribute,
                        "attribute_uilabel": attribute,
                        "param_key": param,
                    }
                )

    def send(self, ident, name):
        self.node("serviceTask", ident, name, {"activityType": "Send"})

    def finish(self, package, deployable):
        plane = self.root.find(".//{" + NS["bpmndi"] + "}BPMNPlane")
        for c in list(plane):
            plane.remove(c)
        nodes = [e for e in self.process if e.tag not in (B + "extensionElements", B + "sequenceFlow")]
        # Put starts first, ends last; branch geometry remains inspectable.
        nodes.sort(key=lambda e: 0 if e.tag == B + "startEvent" else 2 if e.tag == B + "endEvent" else 1)
        for i, n in enumerate(nodes):
            self.coords[n.get("id")] = (150 + i * 150, 150, 110, 65)
        if "ExclusiveGateway_Retry" in self.coords:
            self.coords["CallActivity_Park"] = (610, 310, 110, 65)
            self.coords["ServiceTask_Park"] = (800, 310, 110, 65)
            self.coords["EndEvent_Park"] = (980, 310, 32, 32)
        for ident, (x, y, w, h) in self.coords.items():
            shape = E.SubElement(
                plane, "{" + NS["bpmndi"] + "}BPMNShape", {"id": ident + "_di", "bpmnElement": ident}
            )
            E.SubElement(
                shape, "{" + NS["dc"] + "}Bounds", dict(x=str(x), y=str(y), width=str(w), height=str(h))
            )
        for e in list(self.root.iter()):
            if e.tag not in (B + "messageFlow", B + "sequenceFlow"):
                continue
            a, b = self.coords[e.get("sourceRef")], self.coords[e.get("targetRef")]
            edge = E.SubElement(
                plane,
                "{" + NS["bpmndi"] + "}BPMNEdge",
                {"id": e.get("id") + "_di", "bpmnElement": e.get("id")},
            )
            for x, y in [(a[0] + a[2], a[1] + a[3] / 2), (b[0], b[1] + b[3] / 2)]:
                E.SubElement(edge, "{" + NS["di"] + "}waypoint", {"x": str(x), "y": str(y)})
        params = E.Element("parameters")
        for k in self.parameters:
            p = E.SubElement(params, "parameter")
            for tag, value in [
                ("key", ""),
                ("name", k),
                ("type", "xsd:string"),
                ("isRequired", "true"),
                ("constraint", ""),
                ("description", "Configure before deployment"),
            ]:
                E.SubElement(p, tag).text = value
        refs = E.SubElement(params, "param_references")
        for ref in self.refs:
            E.SubElement(refs, "reference", ref)
        out = io.BytesIO()
        with ZipFile(out, "w", ZIP_DEFLATED) as z:
            for n in ["META-INF/MANIFEST.MF", ".project"]:
                z.writestr(n, self.source.read(n).replace(b"RelaySmoke20260915V2", self.artifact.encode()))
            z.writestr(
                "metainfo.prop",
                "description=Relay messaging scenario - "
                + ("DEV retry test" if deployable else "BROKER CONFIGURATION REQUIRED - DO NOT DEPLOY")
                + "\n",
            )
            z.writestr(
                "src/main/resources/scenarioflows/integrationflow/" + self.artifact + ".iflw",
                E.tostring(self.root, encoding="utf-8", xml_declaration=True),
            )
            z.writestr(
                "src/main/resources/parameters.prop",
                "\n".join(k + "=" + v for k, v in self.parameters.items()),
            )
            z.writestr(
                "src/main/resources/parameters.propdef",
                E.tostring(params, encoding="utf-8", xml_declaration=True),
            )
            for name, code in self.scripts.items():
                z.writestr("src/main/resources/script/" + name, code)
        self.source.close()
        content = base64.b64encode(out.getvalue()).decode()
        return {
            "package_id": package,
            "artifact_id": self.artifact,
            "artifact_content": content,
            "bundle": inspect_bundle(content),
            "configuration_required": not deployable,
            "parameters": self.parameters,
            "deployed": False,
        }


def compile_messaging(spec):
    flows = []
    f = Flow("RelayJMSIngress", "HTTPS → Shared retry work queue")
    f.https("/relay/retry/submit")
    f.script("CallActivity_Validate", "Validate retry envelope", INGRESS)
    f.send("ServiceTask_Queue", "Persist to JMS")
    f.adapter(
        "JMS", "Receiver", queue="Relay_GlobalRetry_Work", channel="MessageFlow_JMS", node="ServiceTask_Queue"
    )
    f.script("CallActivity_Ack", "202 queued acknowledgement", ACK)
    chain = ["StartEvent_2", "CallActivity_Validate", "ServiceTask_Queue", "CallActivity_Ack", "EndEvent_2"]
    for a, b in zip(chain, chain[1:]):
        f.edge(a, b)
    flows.append(f.finish("RelayGlobalRetryJMS", True))
    f = Flow("RelayJMSWorker", "JMS retry worker → process or park")
    f.adapter("JMS", "Sender", queue="Relay_GlobalRetry_Work", retry=spec)
    router = f.node(
        "exclusiveGateway",
        "ExclusiveGateway_Retry",
        "Retry budget exhausted?",
        {"throwException": "true", "raiseAlert": "true"},
    )
    router.set("default", "SequenceFlow_Process")
    f.script("CallActivity_Process", "Process envelope; failures trigger JMS redelivery", WORKER)
    f.script("CallActivity_Park", "Record exhausted retry", PARK)
    f.send("ServiceTask_Park", "Move to parking queue")
    f.node("endEvent", "EndEvent_Park", "Parked", event=True)
    f.adapter(
        "JMS",
        "Receiver",
        queue="Relay_GlobalRetry_Parking",
        channel="MessageFlow_Parking",
        node="ServiceTask_Park",
    )
    f.script(
        "CallActivity_RetryState",
        "Read retry budget",
        IMPORTS
        + """Message processData(Message message) {
        int retries = (message.getHeader('SAPJMSRetries', Object) ?: 0) as int
        message.setProperty('relayPark', retries >= __LIMIT__ ? 'true' : 'false')
        return message
    }
    """.replace("__LIMIT__", str(spec.retry_limit)),
    )
    f.edge("StartEvent_2", "CallActivity_RetryState")
    f.edge("CallActivity_RetryState", "ExclusiveGateway_Retry")
    f.edge("ExclusiveGateway_Retry", "CallActivity_Process", "SequenceFlow_Process")
    f.edge(
        "ExclusiveGateway_Retry",
        "CallActivity_Park",
        "SequenceFlow_Park",
        "${property.relayPark} = 'true'",
    )
    f.edge("CallActivity_Process", "EndEvent_2")
    f.edge("CallActivity_Park", "ServiceTask_Park")
    f.edge("ServiceTask_Park", "EndEvent_Park")
    flows.append(f.finish("RelayGlobalRetryJMS", True))
    for artifact, title, queue, topic, code in [
        (
            "RelayEDAExperience",
            "Experience: HTTPS request → order event",
            None,
            "relay/orders/requested/v1",
            INGRESS,
        ),
        (
            "RelayEDAProcess",
            "Process: validate and calculate order",
            "Relay_Order_Process",
            "relay/orders/validated/v1",
            NORMALIZE,
        ),
        (
            "RelayEDASystem",
            "System: fulfillment projection",
            "Relay_Order_System",
            "relay/fulfillment/requested/v1",
            PROJECT,
        ),
    ]:
        f = Flow(artifact, title)
        if queue:
            f.adapter("AMQP", "Sender", queue=queue)
        else:
            f.https("/relay/events/orders")
        f.script("CallActivity_Transform", title, code)
        f.send("ServiceTask_Publish", "Publish persistent event")
        f.adapter("AMQP", "Receiver", topic=topic, channel="MessageFlow_Solace", node="ServiceTask_Publish")
        chain = ["StartEvent_2", "CallActivity_Transform", "ServiceTask_Publish"]
        if not queue:
            f.script("CallActivity_Ack", "202 published acknowledgement", ACK)
            chain.append("CallActivity_Ack")
        chain.append("EndEvent_2")
        for a, b in zip(chain, chain[1:]):
            f.edge(a, b)
        flows.append(f.finish("RelaySolaceLayeredEDA", False))
    return {
        "flows": flows,
        "retry_policy": spec.model_dump(),
        "scope": "DEV JMS processor test plus unconnected Solace AMQP layered designs; no ERP writes",
    }
