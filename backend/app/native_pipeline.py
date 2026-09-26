"""Compose SAP BPMN topology from a validated design; preview the shipped XML."""

import base64
import copy
import io
import json
import xml.etree.ElementTree as E
from zipfile import ZipFile, ZIP_DEFLATED

from .messaging_designer import Flow
from .order_designer import B, IFL, NS, BASE, props
from .models import inspect_bundle

HEADER = """import com.sap.gateway.ip.core.customdev.util.Message
import groovy.json.JsonSlurper
import groovy.json.JsonOutput
import groovy.util.XmlSlurper
import groovy.xml.MarkupBuilder
import java.math.MathContext
Message processData(Message message) {
"""
HELPERS = """
def getPath = { value, String path -> for (String key : path.tokenize('.')) value=value instanceof Map?value[key]:null; value }
def setPath = { Map target, String path, value -> def keys=path.tokenize('.'); def cur=target; for(int i=0;i<keys.size()-1;i++){ if(!(cur[keys[i]] instanceof Map))cur[keys[i]]=[:];cur=cur[keys[i]] };cur[keys[-1]]=value }
def number = { value -> if(value==null || value instanceof Boolean)throw new IllegalArgumentException('Expected numeric value');new BigDecimal(value.toString()) }
def matches = { c, record ->
 def v=getPath(record,c.source), x=c.value
 if(c.operator=='exists')return v!=null
 if(c.operator=='eq')return v==x
 if(c.operator=='ne')return v!=x
 if(c.operator in ['gt','ge','lt','le']){def n=number(v).compareTo(number(x));return c.operator=='gt'?n>0:c.operator=='ge'?n>=0:c.operator=='lt'?n<0:n<=0}
 if(c.operator=='contains')return v!=null && v.toString().contains(x.toString())
 if(c.operator=='starts_with')return v!=null && v.toString().startsWith(x.toString())
 false
}
"""


def code(config, body, state=True):
    encoded = base64.b64encode(json.dumps(config).encode()).decode()
    setup = "def cfg=new JsonSlurper().parseText(new String('" + encoded + "'.decodeBase64(),'UTF-8'))\n"
    if state:
        setup += "def state=new JsonSlurper().parseText(message.getProperty('relayState').toString());def work=state.work;def row=state.row\n"
    finish = "message.setProperty('relayState',JsonOutput.toJson(state))\n" if state else ""
    return HEADER + HELPERS + setup + body + "\n" + finish + "return message\n}\n"


def compile_native(spec):
    f = Flow(spec.artifact_id, spec.title)
    f.https(spec.endpoint_path)
    collection = bool(spec.collection_path)
    script_rows = {}

    def script(parent, ident, title, source):
        node = copy.deepcopy(f.script_template)
        node.set("id", ident)
        node.set("name", title)
        for child in list(node):
            if child.tag != B + "extensionElements":
                node.remove(child)
        props(node, {"script": ident + ".groovy"})
        parent.append(node)
        f.scripts[ident + ".groovy"] = source
        script_rows[ident] = {"name": title, "script": ident + ".groovy"}
        return ident

    def node(parent, kind, ident, title, values=None):
        n = E.SubElement(parent, B + kind, {"id": ident, "name": title})
        props(n, values or {})
        return n

    def edge(parent, a, b, condition=None, default=False):
        ident = "SequenceFlow_" + a + "_" + b
        e = E.SubElement(parent, B + "sequenceFlow", {"id": ident, "sourceRef": a, "targetRef": b})
        for key, tag in ((a, "outgoing"), (b, "incoming")):
            n = next(x for x in parent if x.get("id") == key)
            E.SubElement(n, B + tag).text = ident
            if default and key == a:
                n.set("default", ident)
        if condition:
            props(e, {"expressionType": "NonXML"})
            E.SubElement(
                e, B + "conditionExpression", {"{" + NS["xsi"] + "}type": "bpmn2:tFormalExpression"}
            ).text = condition

    prepare = """def payload=new JsonSlurper().parseText(message.getBody(String))
def records=cfg.collection_path?getPath(payload,cfg.collection_path):[payload]
if(!(records instanceof List) || records.size()>cfg.max_records)throw new IllegalArgumentException('Invalid collection or record limit exceeded')
if(records.any{!(it instanceof Map)})throw new IllegalArgumentException('Every record must be an object')
records.each{r -> cfg.required_fields.each{path -> def v=getPath(r,path);if(v==null || v instanceof Map || v instanceof List)throw new IllegalArgumentException('Missing or non-scalar required field: '+path)}}
if(cfg.deduplicate_by){def seen=[] as Set;records=records.findAll{r->def key=getPath(r,cfg.deduplicate_by);if(key==null)throw new IllegalArgumentException('Missing deduplication field');seen.add(JsonOutput.toJson(key))}}
if(cfg.collection_path){
 def writer=new StringWriter();new MarkupBuilder(writer).records{records.each{r->record(JsonOutput.toJson(r).getBytes('UTF-8').encodeBase64().toString())};if(!records)record('__EMPTY__')};message.setBody(writer.toString())
}else{message.setProperty('relayState',JsonOutput.toJson([work:records[0],row:[:],drop:false]))}
"""
    script(
        f.process,
        "CallActivity_Validate",
        "Validate input" + (" and deduplicate" if spec.deduplicate_by else ""),
        code(spec.model_dump(), prepare, False),
    )
    edge(f.process, "StartEvent_2", "CallActivity_Validate")
    if collection:
        split = E.parse(BASE / "patterns/splitter.xml").getroot()
        split.set("id", "CallActivity_Split")
        split.set("name", "General Splitter · " + spec.collection_path)
        for c in list(split):
            if c.tag != B + "extensionElements":
                split.remove(c)
        props(
            split,
            {
                "splitExprValue": "/records/record",
                "Streaming": "false",
                "StopOnExecution": "true",
                "ParallelProcessing": "false",
                "grouping": "1",
            },
        )
        f.process.append(split)
        node(
            f.process,
            "callActivity",
            "CallActivity_ProcessRecord",
            "Process each record",
            {"activityType": "ProcessCallElement", "processId": "Process_Record"},
        )
        gather = E.parse(BASE / "patterns/gather.xml").getroot()
        gather.set("id", "CallActivity_Gather")
        gather.set("name", "Gather processed records")
        for c in list(gather):
            if c.tag != B + "extensionElements":
                gather.remove(c)
        f.process.append(gather)
        for a, b in [
            ("CallActivity_Validate", "CallActivity_Split"),
            ("CallActivity_Split", "CallActivity_ProcessRecord"),
            ("CallActivity_ProcessRecord", "CallActivity_Gather"),
        ]:
            edge(f.process, a, b)
        participant = E.SubElement(
            f.collab,
            B + "participant",
            {
                "id": "Participant_Record",
                "name": "Record processing",
                "processRef": "Process_Record",
                IFL + "type": "IntegrationProcess",
            },
        )
        props(participant, {"ifl:type": "IntegrationProcess"})
        parent = E.SubElement(f.root, B + "process", {"id": "Process_Record", "name": "Process one record"})
        props(
            parent,
            {
                "processType": "directCall",
                "transactionTimeout": "30",
                "transactionalHandling": "Required",
                "componentVersion": "1.1",
                "cmdVariantUri": "ctype::FlowElementVariant/cname::LocalIntegrationProcess/version::1.1.2",
            },
        )
        node(parent, "startEvent", "StartEvent_Record", "Record")
        script(
            parent,
            "CallActivity_Decode",
            "Read split record",
            code(
                {},
                "def text=new XmlSlurper().parseText(message.getBody(String)).record.text();def empty=text=='__EMPTY__';def r=empty?[:]:new JsonSlurper().parseText(new String(text.decodeBase64(),'UTF-8'));message.setProperty('relayState',JsonOutput.toJson([work:r,row:[:],drop:empty]))",
                False,
            ),
        )
        edge(parent, "StartEvent_Record", "CallActivity_Decode")
        last = "CallActivity_Decode"
    else:
        parent = f.process
        last = "CallActivity_Validate"

    if spec.mappings:
        source = code(
            [m.model_dump() for m in spec.mappings],
            """if(!state.drop) cfg.each {m ->
 def v=getPath(work,m.source)
 if(m.transform=='uppercase')v=v?.toString()?.toUpperCase(Locale.ROOT)
 if(m.transform=='lowercase')v=v?.toString()?.toLowerCase(Locale.ROOT)
 if(m.transform=='string')v=v?.toString()
 if(m.transform=='number')v=number(v)
 if(m.transform=='boolean' && !(v instanceof Boolean))v=v?.toString()?.toLowerCase() in ['true','1','yes']
 setPath(row,m.target,v);setPath(work,m.target,v)
}""",
        )
        script(parent, "CallActivity_Map", "Map " + ", ".join(m.target for m in spec.mappings), source)
        edge(parent, last, "CallActivity_Map")
        last = "CallActivity_Map"
    for index, calc in enumerate(spec.calculations):
        ident = "CallActivity_Calculate" + str(index)
        script(
            parent,
            ident,
            "Calculate " + calc.target,
            code(
                calc.model_dump(),
                """if(!state.drop){def a=number(getPath(work,cfg.left));def b=cfg.right_value!=null?number(cfg.right_value):number(getPath(work,cfg.right_field));if(cfg.operator=='divide'&&b==0)throw new IllegalArgumentException('Division by zero');def v=cfg.operator=='add'?a+b:cfg.operator=='subtract'?a-b:cfg.operator=='multiply'?a*b:a.divide(b,MathContext.DECIMAL128);setPath(row,cfg.target,v);setPath(work,cfg.target,v)}""",
            ),
        )
        edge(parent, last, ident)
        last = ident
    if spec.filters:
        script(
            parent,
            "CallActivity_Filter",
            "Evaluate record filters",
            code(
                [c.model_dump() for c in spec.filters],
                "if(!state.drop)state.drop=!cfg.every{matches(it,work)}",
            ),
        )
        edge(parent, last, "CallActivity_Filter")
        last = "CallActivity_Filter"
    if spec.routes:
        script(
            parent,
            "CallActivity_RouteCondition",
            "Evaluate routing conditions",
            code(
                [r.model_dump() for r in spec.routes],
                "def index=state.drop?-1:cfg.findIndexOf{matches(it.condition,work)};message.setProperty('relayBranch',index.toString())",
            ),
        )
        edge(parent, last, "CallActivity_RouteCondition")
        router = node(
            parent,
            "exclusiveGateway",
            "ExclusiveGateway_Route",
            "Route by business rules",
            {"throwException": "true", "raiseAlert": "true"},
        )
        edge(parent, "CallActivity_RouteCondition", router.get("id"))
        ends = []
        for index, label in enumerate([r.label for r in spec.routes] + [spec.default_route]):
            ident = "CallActivity_Branch" + str(index)
            script(
                parent,
                ident,
                label,
                code(
                    {"field": spec.status_field, "label": label},
                    "if(!state.drop)setPath(row,cfg.field,cfg.label)",
                ),
            )
            edge(
                parent,
                router.get("id"),
                ident,
                None if index == len(spec.routes) else "${property.relayBranch} = '" + str(index) + "'",
                index == len(spec.routes),
            )
            ends.append(ident)
    else:
        ends = [last]
    script(
        parent,
        "CallActivity_RecordResult",
        "Write record result",
        code(
            {"passthrough": not (spec.mappings or spec.calculations or spec.routes)},
            """def output=state.drop?[]:[cfg.passthrough?work:row]
message.setProperty('relayOutput',JsonOutput.toJson(output))
def writer=new StringWriter();new MarkupBuilder(writer).result(JsonOutput.toJson(output).getBytes('UTF-8').encodeBase64().toString());message.setBody(writer.toString())""",
        ),
    )
    for end in ends:
        edge(parent, end, "CallActivity_RecordResult")
    if collection:
        node(parent, "endEvent", "EndEvent_Record", "Record processed")
        edge(parent, "CallActivity_RecordResult", "EndEvent_Record")
        last = "CallActivity_Gather"
    else:
        last = "CallActivity_RecordResult"
    response = """def output=[]
if(cfg.collection_path){new XmlSlurper().parseText(message.getBody(String)).depthFirst().findAll{it.name()=='result'}.each{output.addAll(new JsonSlurper().parseText(new String(it.text().decodeBase64(),'UTF-8')))}}else{output=new JsonSlurper().parseText(message.getProperty('relayOutput').toString())}
if(cfg.sort_by)output.sort{a,b->def av=getPath(a,cfg.sort_by),bv=getPath(b,cfg.sort_by);def n=(av==null&&bv==null)?0:av==null?1:bv==null?-1:(av<=>bv);cfg.sort_descending?-n:n}
if(cfg.output_fields!=null)output=output.collect{r->def selected=[:];cfg.output_fields.each{path->setPath(selected,path,getPath(r,path))};selected}
message.setHeader('Content-Type','application/json');message.setHeader('CamelHttpResponseCode',200)
message.setBody(JsonOutput.toJson(cfg.collection_path?[(cfg.output_collection):output,count:output.size()]:(output?output[0]:[:])))"""
    script(
        f.process,
        "CallActivity_Response",
        "Sort and shape response" if spec.sort_by else "Shape JSON response",
        code(spec.model_dump(), response, False),
    )
    edge(f.process, last, "CallActivity_Response")
    edge(f.process, "CallActivity_Response", "EndEvent_2")
    sub = node(
        f.process,
        "subProcess",
        "SubProcess_Error",
        "Exception Subprocess",
        {
            "cmdVariantUri": "ctype::FlowstepVariant/cname::ErrorEventSubProcessTemplate",
            "activityType": "ErrorEventSubProcessTemplate",
        },
    )
    start = node(sub, "startEvent", "StartEvent_Error", "Error")
    E.SubElement(start, B + "errorEventDefinition")
    script(
        sub,
        "CallActivity_Error",
        "Return safe error",
        code(
            {},
            "message.setHeader('Content-Type','application/json');message.setHeader('CamelHttpResponseCode',400);message.setBody(JsonOutput.toJson([error:'Input validation or processing failed',handler:'exception_subprocess']))",
            False,
        ),
    )
    end = node(sub, "endEvent", "EndEvent_Error", "Error response")
    E.SubElement(end, B + "messageEventDefinition")
    edge(sub, "StartEvent_Error", "CallActivity_Error")
    edge(sub, "CallActivity_Error", "EndEvent_Error")
    xml = layout(f.root)
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as z:
        for name in [
            "META-INF/MANIFEST.MF",
            ".project",
            "src/main/resources/parameters.prop",
            "src/main/resources/parameters.propdef",
        ]:
            z.writestr(name, f.source.read(name).replace(b"RelaySmoke20260915V2", spec.artifact_id.encode()))
        z.writestr("metainfo.prop", "description=Relay native BPMN composition\n")
        z.writestr("src/main/resources/scenarioflows/integrationflow/" + spec.artifact_id + ".iflw", xml)
        for name, source in f.scripts.items():
            z.writestr("src/main/resources/script/" + name, source)
    f.source.close()
    content = base64.b64encode(out.getvalue()).decode()
    return {
        "artifact_content": content,
        "bundle": inspect_bundle(content),
        "bpmn_xml": xml.decode(),
        "scripts": f.scripts,
        "steps": [r["name"] for r in script_rows.values()],
        "configuration_required": False,
    }


def layout(root):
    """Lay out actual nodes, including local processes, route branches and error scopes."""
    plane = root.find(".//{" + NS["bpmndi"] + "}BPMNPlane")
    plane.clear()
    plane.set("id", "BPMNPlane_1")
    plane.set("bpmnElement", "Collaboration_1")
    positions = {"Participant_1": (15, 90, 65, 100)}
    y = 40
    for process in root.findall(B + "process"):
        participant = next(
            n for n in root.iter(B + "participant") if n.get("processRef") == process.get("id")
        )
        nodes = [
            n for n in process if n.tag not in (B + "extensionElements", B + "sequenceFlow", B + "subProcess")
        ]
        depths = {n.get("id"): 0 for n in nodes if n.tag == B + "startEvent"}
        edges = process.findall(B + "sequenceFlow")
        for _ in nodes:
            for e in edges:
                if e.get("sourceRef") in depths:
                    depths[e.get("targetRef")] = max(
                        depths.get(e.get("targetRef"), 0), depths[e.get("sourceRef")] + 1
                    )
        lanes = {}
        max_lane = 0
        for n in nodes:
            d = depths.get(n.get("id"), 0)
            lane = lanes.get(d, 0)
            lanes[d] = lane + 1
            max_lane = max(lane, max_lane)
            event = n.tag in (B + "startEvent", B + "endEvent")
            gateway = n.tag == B + "exclusiveGateway"
            positions[n.get("id")] = (
                140 + d * 190,
                y + 65 + lane * 100,
                36 if event else 45 if gateway else 150,
                36 if event else 45 if gateway else 65,
            )
        width = 230 + max(depths.values()) * 190
        height = 170 + max_lane * 100
        for sub in process.findall(B + "subProcess"):
            positions[sub.get("id")] = (220, y + height, 650, 150)
            for i, n in enumerate(
                n for n in sub if n.tag in (B + "startEvent", B + "callActivity", B + "endEvent")
            ):
                positions[n.get("id")] = (
                    260 + i * 200,
                    y + height + 55,
                    150 if n.tag == B + "callActivity" else 36,
                    60 if n.tag == B + "callActivity" else 36,
                )
            height += 170
        positions[participant.get("id")] = (100, y, max(width, 800), height)
        y += height + 60
    for ident, (x, y, w, h) in positions.items():
        shape = E.SubElement(
            plane, "{" + NS["bpmndi"] + "}BPMNShape", {"id": ident + "_di", "bpmnElement": ident}
        )
        if ident.startswith("SubProcess"):
            shape.set("isExpanded", "true")
        E.SubElement(shape, "{" + NS["dc"] + "}Bounds", dict(x=str(x), y=str(y), width=str(w), height=str(h)))
    for e in root.iter():
        if e.tag not in (B + "sequenceFlow", B + "messageFlow"):
            continue
        a, b = positions[e.get("sourceRef")], positions[e.get("targetRef")]
        edge = E.SubElement(
            plane, "{" + NS["bpmndi"] + "}BPMNEdge", {"id": e.get("id") + "_di", "bpmnElement": e.get("id")}
        )
        for x, y in [(a[0] + a[2], a[1] + a[3] / 2), (b[0], b[1] + b[3] / 2)]:
            E.SubElement(edge, "{" + NS["di"] + "}waypoint", dict(x=str(x), y=str(y)))
    return E.tostring(root, encoding="utf-8", xml_declaration=True)
