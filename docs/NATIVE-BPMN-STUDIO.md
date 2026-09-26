# Native BPMN studio — 2026-09-23

## What changed

The former general compiler put a configurable pipeline inside one Groovy task. That changed behavior but left the same SAP diagram for different descriptions. The new compiler emits different connected BPMN structures: single-object mapping stays in the main process; collections add a General Splitter, a local process and Gather; conditional routing adds an exclusive gateway and one branch per rule plus the default; each calculation has its own visible task. Mapping, filtering and response shaping remain reviewed script implementations. Multi-step formulas can project only final output fields.

The model fills a validated operation schema. It does not choose a named business scenario or supply executable source. The obsolete scenario classifier and single-script interpreter were removed. This is still a constrained HTTPS JSON compiler, not support for every SAP adapter or arbitrary BPMN graph.

## Review and execution

1. Select an existing package and describe the scenario.
2. Optionally provide JSON input and the exact expected JSON output. These are sent with the description to the configured free model. A simulation mismatch permits one bounded semantic correction using the previous design and actual output. If the corrected design still differs, no approval run is created. Neither sample values nor expected results may be hardcoded into the design.
3. Inspect the BPMN preview, step properties, scripts, evidence and proposed destination. Export the BPMN or ZIP if needed.
4. Approve the immutable plan. The bundle shown in the viewer is byte-identical to the XML in that plan's ZIP.
5. Follow upload, deployment, runtime verification and audit. Functional input/output tests are distinct from deployment status.

Changing the description, package or acceptance sample invalidates the displayed draft. The model has no permission to approve changes. The BPMN viewer uses locally bundled bpmn-js 18.6.3 under its included license; it loads no remote JavaScript. SAP is the execution engine; bpmn-js renders the design and LangGraph checkpoints the deployment workflow.

## Research scope

Generation ranks reviewed SAP pattern guidance by the description and retrieves bounded README excerpts from the official `SAP-samples/ai-enabled-integrations-codejam` and `SAP-samples/codejam-code-based-agents` repositories. Retrieval is cached for one hour, limited to fixed public URLs with timeouts and size bounds, and its availability is exposed in the UI. Unavailable content is marked unavailable. Retrieved text is untrusted evidence, not instructions. This does not automatically browse the full Discover catalog or promise a new internet search for every prompt.

## Verification

See [machine-readable tenant results](native-bpmn-acceptance.json) for artifact IDs and exact inputs/outputs. Invoice, inventory, employee and temperature-conversion cases were generated from descriptions, approved through the backend API, deployed to `RelayTest`, and invoked through authenticated HTTPS. Their saved SAP BPMN topology and STARTED runtime status were read back. The additional support-ticket scenario was generated with explicit acceptance criteria in the refactored UI, reviewed and approved there, then invoked successfully over HTTPS. Ten additional runtime checks covered malformed JSON, missing required fields, empty batches and record limits; exception responses were verified as HTTP 400 with the exception-subprocess marker. All 92 local tests pass, including bounded semantic correction and refusal to create a plan after a persistent mismatch.

An initial invoice deployment returned a transient SAP HTTP 500 after upload. Inspection and a deliberate later deployment showed that artifact STARTED. The application did not blindly replay the ambiguous write. The subsequent acceptance run completed successfully; the initial failed run remains visible in Activity for audit.

The browser checks verified actual employee and ticket BPMN diagrams, the awaiting-approval and succeeded states, narrow side-panel rendering, desktop layout bounds, and removal of the old approval when the description changed. The refactored layout removes the large landing-page headline and separates Describe, Diagram and Review & deploy. Desktop has a dedicated canvas; narrow panels switch between the three panes. The extension archive must be reloaded in Chrome to pick up this UI update; browser installation was not performed by this test.

## Limits

- No generic SFTP/OData/SOAP/ERP/email receiver generation yet. Unsupported descriptions return questions rather than a substituted response-only flow.
- Research and model output can be incomplete. The preview, acceptance criteria and approval remain necessary.
- The visual editor is read-only. Change the description and regenerate; arbitrary drag-and-drop edits would also need SAP-specific validation and a fresh approval.
- Local simulation is not a guarantee of identical numeric precision for every payload; SAP runtime uses Groovy BigDecimal while the simulator uses Python numbers. The supplied live examples verify concrete outputs.
- WhatsApp and Solace connection setup remain separate from this studio change.
