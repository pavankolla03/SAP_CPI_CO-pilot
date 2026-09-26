# API and tool contracts

All `/v1` routes require `Authorization: Bearer <opaque key>`. Identity comes only from server configuration. There is no request-level tenant override. Missing/invalid credentials return 401; insufficient role returns 403; an inaccessible run returns 404; invalid body returns 422; state/policy conflicts return 409. SAP upstream failures return sanitized 502, or 404 for missing resources. Readiness `/health` only reports process health, not SAP access.

## Reads (all roles)

- `GET /v1/me`: tenant ID/name, actor, role, mode, DEV environment and upload capability.
- `GET /v1/packages`: OData packages as an array; pagination is followed for at most 20 pages.
- `GET /v1/packages/{id}`: package metadata.
- `GET /v1/packages/{id}/iflows`: design-time artifacts in a package.
- `GET /v1/iflows/{id}?version=active`: design-time metadata.
- `GET /v1/iflows/{id}/runtime`: runtime artifact, including SAP `Status`.
- `GET /v1/iflows/{id}/mpl`: latest 20 MPL summaries; never message bodies or attachments. These are contextual history, not correlated proof that this run sent a message.
- `GET /v1/deployments/{task_id}`: SAP build/deployment status.
- `GET /v1/runs`: last 100 owned run IDs/timestamps.
- `GET /v1/runs/{id}`: plan, plan_hash, pending interruptions, status, observations, generated test and ordered events. Upload bytes and credentials are not returned.

## Propose (operator or approver)

`POST /v1/runs` returns 201 with the run snapshot. It performs read-only discovery and pauses before writes. Expected discovery failures produce a run with `needs_attention` and an error event; inspect the returned status even on 201.

```json
{
  "goal": "Deploy the reviewed HelloWorld integration",
  "action": "deploy",
  "package_id": "AgentSandbox",
  "artifact_id": "HelloWorld",
  "name": "Agent Sandbox",
  "version": "active",
  "artifact_content": null
}
```

Actions: `create_package`, `deploy`, `upload_deploy`, `create_partner_parameter`. The goal is bounded text for human context, not a prompt executed by a model. `upload_deploy` requires base64 ZIP content, a new artifact ID, an existing package, upload capability, and version `active`. ZIP limits: 4 MB compressed, 20 MB expanded, 300 entries; no traversal or duplicate paths; manifest and parseable `.iflw` required. No archive is extracted on disk. `create_package` requires an unused ID. `deploy` requires matching package ownership of the artifact. IDs and versions only accept ASCII letters, digits, `.`, `_` and `-` to prevent OData/path injection.

## Decide and recover (approver only)

`POST /v1/runs/{id}/decision`:

```json
{"approve": true, "plan_hash": "64-character-sha256-from-the-run"}
```

A matching pending interrupt and digest are mandatory. Replaying the decision after completion returns 409. The run's stored plan cannot be edited through this endpoint. Human identity is recorded server-side. `approve: false` rejects the initial plan; for repair it stops with `needs_attention`.

A repair decision approves only one retry of an unchanged existing artifact after a conclusive failed build. There is no patch generation or implicit retry after timeout. Corrected bundles must be proposed under a new artifact ID through a new plan. Every new proposal needs new approval.

`POST /v1/runs/{id}/resume` with `{}` resumes a nonterminal graph checkpoint after interruption or a recoverable read failure. It cannot bypass a pending approval or replay an ambiguous write. Completed graphs return 409. A `needs_attention` run at END is terminal: use the read APIs for inspection, then create a new plan if appropriate.

Requests are synchronous and may wait for bounded polling or network timeouts; the UI separately polls run events every two seconds. Closing the panel does not cancel server work. After a process crash, use History to find the persisted run. Multi-worker execution is unsupported in this release.

## Internal write contracts

- `create_package(request)` → POST `IntegrationPackages`, JSON `Id`, `Name`, `ShortText`.
- `upload(request)` → POST `IntegrationDesigntimeArtifacts`, JSON `Id`, `Name`, `PackageId`, `ArtifactContent`.
- `deploy(request)` → POST `DeployIntegrationDesigntimeArtifact`, quoted `Id` and `Version` OData query values; returns normalized `{task_id}`.
- `build(task_id)` → GET `BuildAndDeployStatus(TaskId='...')`.
- `runtime(id)` → GET `IntegrationRuntimeArtifacts('...')`.

Live writes obtain OAuth using client credentials, fetch CSRF from the service root, and retain cookies in the same HTTP client. Redirects are disabled; upstream bodies are not included in errors. Token expiry is cached; authentication/CSRF/write failures are not automatically retried. OData continuations must stay under the configured API root. The journal records write intent before dispatch, stores completed results, and blocks replay for unresolved intent. A local journal cannot prove whether SAP accepted a timed-out request; the operator must inspect the tenant.

## MCP surface

`list_packages`, `read_package`, `list_iflows`, `read_iflow`, `runtime_status`, `message_logs`, `deployment_status`, `propose_run`, `inspect_run` are actual MCP SDK tools with schemas inferred from Python types/Pydantic. stdio transport is local; configure one tenant-scoped backend token per server process. No arbitrary URL, approval, raw write, shell or unrestricted SAP endpoint tool is exposed.


## Added: free-model proposals and service adapters

- `GET /v1/planner`: configured model IDs, key-slot count and free-only status, never secrets.
- `POST /v1/proposals` (operator/approver): `{ "goal": "Create a DEV package with package_id Example and name Example" }` → validated draft plus model ID and key-slot index. `supported: false` means no draft is available. No run is created. The caller must submit the reviewed request to `/v1/runs` and then approve its plan. Invalid model output, paid/unavailable model, rate limits or network failures stop without side effects.
- `GET /v1/capabilities`: independent statuses (`accessible`, `blocked`, `not_configured`, `not_implemented`) for configured services. In demo mode accessible means the demo adapter only. Read access does not imply write permission.
- `GET /v1/apim/proxies`: first proxy inventory page using a separate API Portal connection.
- `GET /v1/aem/services`: first Advanced Event Mesh broker-service inventory page using a separate AEM token.
- `GET /v1/b2b/parameters`: first 20 partner parameter IDs (Pid/Id), without values.
- `GET /v1/b2b/partners/{partner_id}/parameters/{parameter_id}`: one partner parameter including its value.

`create_partner_parameter` requests use `partner_id`, `parameter_id` and `parameter_value` (maximum 1000 characters). Existing entries cannot be overwritten. The collection must be readable before an entity 404 is treated as absence. Exact parameter content is included in the plan and read-back smoke test. Do not place credentials in string parameters through this pilot UI.

MCP additionally exposes `service_capabilities`, `apim_proxies`, `aem_services` and `partner_parameters`; there were 13 tools before the diagnostics addition. The model proposal route is independent of MCP; external MCP hosts may use their own model but cannot approve.

## SAP API diagnostics

`GET /v1/diagnostics` is authenticated and resolves the tenant from the caller's server-owned identity. It takes no URL, tenant ID or credential input. Returns `mode`, `environment`, `checks`, `read_ready`, `write_access` and `detail`. Each check has a fixed name/path, status and safe detail; failures may add `phase`, `upstream_status`, and `next_step`. Demo mode returns no live checks and `read_ready=false`. `read_ready` means all five sampled reads worked, not that deployment is authorized. Each request uses `$top=1`; monitoring and Partner Directory probes select identifiers, while design APIs omit unsupported `$select`. Design artifacts are checked through the first readable package. Returned rows are discarded; no continuation is followed. MCP tool `diagnose_sap_apis` exposes the same read-only result (14 tools total).

## Scenario designer

The order proposal/compile API schemas and two additional MCP tools are documented in [IFLOW-DESIGNER.md](IFLOW-DESIGNER.md). Compilation is local and has no SAP side effects. The compiled ZIP uses the existing new-artifact approval workflow.

## Messaging patterns and design-only upload

`POST /v1/designs/messaging/compile` returns five bounded artifacts. `RunRequest.action=upload` requires a ZIP, binds its hash to approval, enforces new artifact IDs and upload permission, and performs design-time read-back without deployment. See [messaging guide](MESSAGING-AND-VOICE.md).

Voice, description-first and channel job contracts: [VOICE-WHATSAPP.md](VOICE-WHATSAPP.md).
