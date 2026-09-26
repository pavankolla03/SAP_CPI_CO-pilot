# Scenario-to-iFlow designer

The primary `/v1/scenarios/compile` workflow now translates a description into a validated intermediate `PipelineDesign`, then compiles it with reviewed code. It does not classify the request into an order or mapping template. The schema composes:

- single-object or collection processing;
- required-field validation and record limits;
- nested field mappings and type/case conversions;
- addition, subtraction, multiplication and division;
- filtering, deduplication and sorting;
- ordered conditional routes with a default result;
- configurable response collection names.

The model cannot emit executable Groovy. The compiler composes native Splitter/Gather and Router structures, with separate reviewed scripts for mapping, each calculation, filtering and response shaping. The exact bundled BPMN XML is previewed before approval. External adapters remain separate compiler modules because their SAP adapter versions, endpoints, authentication aliases and delivery semantics must be configured explicitly.

The earlier native batch-order compiler remains available through `/v1/scenarios/orders` and Advanced tools. It generates native Splitter, Router, Gather and Exception Subprocess elements for that specialized pattern.

## Order contract

POST JSON to the deployed authenticated HTTPS endpoint with `orders`, a non-empty array of up to `max_orders` (default and maximum 100). Each item has:

- `id`: unique within the batch; 1–64 letters, digits, underscores or hyphens.
- `amount`: numeric unit value, 0–1,000,000,000.
- `quantity`: numeric integer, 1–10,000.

The flow converts the validated envelope to internal XML, then uses a native **General Splitter** with XPath `/orders/order`, grouping 1, sequential processing and Stop on Exception disabled. Each split goes to a **Local Integration Process**, calculates `amount × quantity`, and uses a native **Router**:

- Invalid amount or quantity → `REJECTED`.
- Total strictly above `review_threshold` (default 1000) → `REVIEW`.
- Otherwise → `ACCEPTED`.

Each response retains its input ID. Invalid JSON, invalid/missing IDs, duplicate IDs and invalid batch sizes reject the entire batch with HTTP 400 through the batch **Exception Subprocess**. A local Exception Subprocess returns an `ERROR` result for an unexpected order failure and allows subsequent orders to continue. **Gather** collects the XML results; a final script returns JSON with `orders` and `count`.

HTTP 200 means a batch result is available; callers must inspect every order's status. These are processing decisions, not confirmations that an ERP sales order was created. Duplicate IDs are rejected, not grouped. There is no persistent deduplication across requests, database write, receiver call, currency conversion, inventory reservation, durable retry or transaction rollback across orders. Review means a returned status; a human task service is not yet connected.

## Side-panel workflow

1. Connect the backend and choose an existing destination package in **Describe**.
2. Describe the complete scenario, add corrections or configuration answers, and optionally provide sample input and exact expected output.
3. **Analyze solution** creates a read-only, persisted architecture plan. Review its requirements, flow boundaries, evidence, assumptions, questions and blockers.
4. For a fully covered single HTTPS JSON flow, **Build diagram** compiles the frozen plan once. Inspect the exact BPMN, scripts, test cases and bundle fingerprint.
5. **Review & deploy** creates an immutable awaiting-approval run. An approver separately approves the upload and deployment.
6. Check deployment status, runtime response and MPL evidence. Build success alone is not runtime success, and MPL completion alone is not business success.

Changing design inputs invalidates the compiled ZIP. The compiler never executes model-generated code. SAP scripts are fixed reviewed templates with bounded numeric settings. Neither MCP design tool can approve deployment.

## API and tools

All endpoints require a tenant-scoped bearer token; proposal and compilation require operator/approver.

- `POST /v1/scenarios/compile`: `{description, package_id, pattern:"auto"}`. Returns clarification or a typed pipeline, compiled bundle, test descriptions and awaiting-approval run. This is the default side-panel workflow.
- The default compiler currently accepts synchronous HTTPS JSON scenarios. External adapters are rejected with configuration questions instead of being simulated.
- `POST /v1/solutions/analyze`: `{description, package_id, clarifications?, sample_input?, expected_output?}`. Returns the persisted architecture, requirement evidence, questions, blockers, references and acceptance result without creating an SAP write plan.
- `GET /v1/solutions/{plan_id}`: returns the same tenant-scoped solution plan.
- `POST /v1/solutions/{plan_id}/build`: compiles the frozen buildable plan and returns one awaiting-approval run. Repeating the request returns that same run.

- `POST /v1/designs/orders/propose`: `{scenario, package_id, artifact_id, endpoint_path}`. Returns `{draft:{supported,explanation,questions,design},model,cost,references}`. This calls verified zero-price OpenRouter models; unsupported scenarios stay unsupported.
- `POST /v1/designs/orders/compile`: `{pattern:"batch_orders",title,package_id,artifact_id,endpoint_path,review_threshold,max_orders}`. Returns a base64 artifact, SHA-256/file inventory, steps, scripts, sample input and test case descriptions. Does not write to SAP.
- `GET /v1/designs/knowledge?q=...`: curated official references; not a live Discover mirror.
- MCP `propose_order_design` and `compile_order_design` wrap the corresponding APIs. Pass the compiled artifact to the existing `propose_run` workflow; approval remains separate.

The separate `/v1/designs/propose` and `/v1/designs/compile` endpoints are an experimental scalar JSON mapping compiler. Only the batch-order pattern has the live acceptance evidence described below.

## SAP knowledge sources and provenance

The knowledge hub currently contains curated official references and inspected native sample elements. It does **not** index every Discover package or automatically copy content from Discover. Selected SAP content can require different licenses and tenant entitlements; each future import needs source/version tracking and configuration review.

- [SAP Discover: Enterprise Integration Patterns](https://hub.sap.com/package/DesignGuidelinesPatterns/overview).
- [SAP recipes: knowing when all split records finish](https://github.com/SAP/apibusinesshub-integration-recipes/tree/7005c8cc819c0846c0261cf8246bcacc298da6ee/Recipes/for/How%20to%20determine%20when%20all%20split%20messages%20are%20processed): native Splitter and Gather serialization.
- [SAP recipes: ExactlyOnce handling](https://github.com/SAP/apibusinesshub-integration-recipes/tree/7005c8cc819c0846c0261cf8246bcacc298da6ee/Recipes/for/ExactlyOnce%20handling%20in%20Cloud%20Platform%20Integration): local process, Router and Exception Subprocess structure. This project does not implement the recipe's exactly-once persistence.
- [SAP: splitter exception handling](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/handle-exceptions-when-using-splitter-pattern).
- [SAP: integration flow API requests](https://help.sap.com/docs/SAP_INTEGRATION_SUITE/9519789d5664487f8b9cd89eba514477/d4c97116fdc14913b93d1a16768f67d8.html).

Sample repository revision: `7005c8cc819c0846c0261cf8246bcacc298da6ee`. Retained templates and modifications are under `backend/templates/patterns`, with Apache-2.0 license and notice. The HTTPS base is the sanitized template previously verified on this DEV tenant. No customer business mapping is included.

## Next phases

1. Add versioned selection and approved copy/import of chosen Discover packages, with provenance and license metadata.
2. Expand typed, tested compiler patterns: external receivers, mappings, authentication aliases and business-specific route predicates. Never silently substitute response-only processing for a requested receiver operation.
3. Add approved updates with content-hash concurrency checks and rollback snapshots; current UI creates new artifact IDs only.
4. Persist idempotency and retries, add receiver contract tests, and build a representative scenario evaluation suite before widening autonomy.

See [live order acceptance](ORDER-ACCEPTANCE-20260916.md) for actual test results and limitations.
