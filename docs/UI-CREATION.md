# Package and iFlow creation

Relay has persistent left navigation with separate **Create package** and **Create iFlow** screens. The studio separates the description form, BPMN canvas and deployment review. In the narrow Chrome side panel, use **Describe**, **Diagram** and **Review & deploy** to switch panes without scrolling through a single long form.

1. Create package: enter its name and ID, review, then press **Create package**. On success it becomes available in the iFlow package selector.
2. Create iFlow: choose an existing SAP package and describe the input, processing rules and output. Three structurally different editable examples are provided. The screen always identifies the destination package and shows Relay's interpretation. Press **Design my iFlow** to prepare a typed design and an approval plan.
3. Review the design, scripts and destination. Press **Create iFlow & deploy** to upload and deploy. Generation alone does not create an SAP artifact.
4. A successful result names the artifact and package. **View in package** reads the SAP package's iFlows so the created artifact can be checked immediately.

Voice input is collapsed. The legacy fixed order template is hidden from this screen. Existing-artifact deployment, ZIP upload and messaging templates are under **Advanced tools**. Activity preserves earlier plans and runs.

During browser testing, the free model intermittently returned a malformed proposal before any upload. The planner now performs one bounded formatting retry, retaining schema validation, zero-price checks and rate-limit cooldown. A second invalid response stops generation and the UI displays the failure instead of leaving a “Generating” message. Unsupported scenarios still require clarification.

The default description workflow composes a validated HTTPS JSON pipeline from required fields, nested mappings, case/type transforms, arithmetic, filters, deduplication, sorting, conditional routing, collection processing and response shaping. The model produces data in this schema; it never supplies executable Groovy. The native compiler creates visible processing steps and connections, including Splitter/Gather for collections and Router branches for conditional routing. The BPMN viewer shows the actual proposed artifact. Optional acceptance input/output mismatches stop generation before approval.

External receivers and senders require adapter-specific compiler modules and connection configuration. Relay returns clarification for SFTP, SOAP, OData, AS2, mail, Kafka, JMS, AMQP, database and ERP-write requests that cannot yet be compiled accurately. It never substitutes a local response for a requested external operation.
