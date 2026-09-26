> Update: the new management key passed live DEV acceptance on 2026-09-15. See [current acceptance results](LIVE-ACCEPTANCE-20260915.md). Earlier failures below refer to the previous key or diagnostics.

# SAP API implementation research

Research date: 2026-09-15. This is an engineering reference for Relay, not evidence that the tenant supports every capability.

## Decision

Keep the FastAPI backend calling documented SAP management APIs through a bounded adapter. Use SAP Project Piper as the first reference for upload/deploy/integration-test behavior; use CodeJam examples for agent structure. Avoid adding a Node or Go service just to wrap calls already implemented in Python. Open-source clients do not replace a subscribed SAP service, correct service endpoint or API permissions. API availability depends on the SAP service plan: [SAP content management documentation](https://help.sap.com/docs/integration-suite/sap-integration-suite/manage-integration-content).

## Cloud Integration operations

The official [Integration Content OData API guide](https://help.sap.com/docs/cloud-integration/sap-cloud-integration/d1679a80543f46509a7329243b595bdb.html?state=PRODUCTION&version=Cloud) covers artifacts and directs API clients to the required permissions. Relay currently implements these paths beneath the administrator-configured `/api/v1` management base:

- `GET IntegrationPackages` and `GET IntegrationPackages('id')`: list/read packages.
- `POST IntegrationPackages`: create a package with ID, name and description.
- `GET IntegrationPackages('id')/IntegrationDesigntimeArtifacts`: list package iFlows.
- `GET IntegrationDesigntimeArtifacts(Id='id',Version='active')`: read design-time metadata.
- `POST IntegrationDesigntimeArtifacts`: upload base64 ZIP content into a package; tenant upload flag and approval required.
- `POST DeployIntegrationDesigntimeArtifact`: deploy the selected ID/version; record the task ID before polling.
- `GET BuildAndDeployStatus(TaskId='id')`: observe the deployment task.
- `GET IntegrationRuntimeArtifacts('id')`: verify runtime state.
- `GET MessageProcessingLogs`: retrieve filtered message metadata, excluding payloads.

These describe Relay's implemented contracts, not a claim that all operations passed live. Validate responses and artifact format against the selected tenant before proceeding. A deployment success is distinct from successful processing of a test message.

SAP's [Piper upload step](https://www.project-piper.io/steps/integrationArtifactUpload/) explicitly requires the Process Integration Runtime `api` plan service key. Its [deployment step](https://www.project-piper.io/steps/integrationArtifactDeploy/) and [integration-test step](https://www.project-piper.io/steps/integrationArtifactTriggerIntegrationTest/) are useful reference implementations. [SAP's CI/CD setup guide](https://help.sap.com/docs/continuous-integration-and-delivery/sap-continuous-integration-and-delivery/configure-sap-integration-suite-artifacts-job-in-your-repository) distinguishes the management API key from the integration-flow key used to invoke an iFlow. Relay still needs a separately configured, allowlisted runtime test endpoint and appropriate runtime authentication for a real business-message smoke test.

## API Management

Use the documented API Portal API access flow and a separate service connection. Relay has a read-only proxy-list adapter at `/apiportal/api/1.0/Management.svc/APIProxies`. Project Piper includes API proxy and provider lifecycle steps, providing an implementation reference for the next phase: [Piper step index](https://www.project-piper.io/steps/integrationArtifactUpload/). Do not send a Cloud Integration token to a guessed API Portal host. Proxy writes, policy updates and publication are not implemented or live-tested in Relay.

## B2B and Trading Partner Management

Partner Directory is a useful building block: Relay lists/reads string parameters and can propose an approved parameter creation. SAP documents OData access to [Partner Directory entries](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/managing-partner-directory-entries?q=manage+data+store).

Full [Trading Partner Management](https://help.sap.com/docs/integration-suite/sap-integration-suite/trading-partner-management?q=API+Designer) includes profiles, agreements, communication requirements and runtime artifacts. It is not equivalent to setting Partner Directory parameters. No verified public profile/agreement write contract was established in this research; do not build guessed TPM endpoints. Confirm the supported API catalog and tenant entitlements before adding those tools. [TPM permissions](https://help.sap.com/docs/SAP_INTEGRATION_SUITE/51ab953548be4459bfe8539ecaeee98d/eb14b2279fca422d9b64b6525a23fbdf.html) also distinguish administrative and sensitive-data operations.

## Advanced Event Mesh

The official [AEM REST service guide](https://help.pubsub.em.services.cloud.sap/Cloud/ght_use_rest_api_services.htm) describes service management APIs. Relay's initial adapter reads `/api/v2/missionControl/eventBrokerServices` with its separately configured token. Broker management, broker data-plane publishing/consuming and Cloud Integration OData are different interfaces. Queue/subscription changes and publish/consume acceptance tests remain future work. [SAP's event-driven CodeJam](https://github.com/SAP-samples/event-driven-integrations-codejam) is a useful tutorial reference, not a substitute for an AEM service instance.

## Open-source resources to reuse selectively

- [SAP Project Piper](https://github.com/SAP/jenkins-library): first choice for studying proven SAP CI/CD operation contracts. Keep the bounded Python execution layer; use Piper in a future isolated CI worker if needed.
- [SAP AI-enabled integrations CodeJam](https://github.com/SAP-samples/ai-enabled-integrations-codejam): reference for AI-enabled integration scenarios and MCP learning. Keep sample tenant configuration out of production code.
- [SAP code-based agents CodeJam](https://github.com/SAP-samples/codejam-code-based-agents): Python/JavaScript agent examples, including LangGraph. Reuse architecture ideas for tools and SAP AI integration; its examples do not supply Relay's tenant isolation or approval policy.
- [FlashPipe](https://github.com/engswee/flashpipe): Apache-2.0 CI/CD companion. Evaluate for artifact lifecycle automation. Its current README states analytics are always enabled; assess that before embedding the binary in customer workers.
- [CPILint](https://github.com/mwittrock/cpilint): governance/linting candidate for the validate stage. Run against isolated artifacts and record the rule set/version; passing lint is not a runtime integration test.
- [Contiva SAP Integration Suite client](https://github.com/contiva/sap-integration-suite-client): community Node client with OAuth/CSRF and content/log clients. Useful for comparing contracts; not adopted as a dependency in this Python backend. Review its exact license and release before any code reuse.

No third-party source code or binaries were imported in this change. Pin releases/commits and retain notices before future dependency adoption.

## Built from this research

Added authenticated `GET /v1/diagnostics`, MCP `diagnose_sap_apis`, and the Connections → Diagnose SAP APIs control. Five bounded read probes distinguish package, design artifact, runtime artifact, message log and Partner Directory access. Responses preserve upstream HTTP status and failure phase without returning credentials, message payloads or upstream bodies. OAuth failure stops remaining preflight checks. Reads never certify write permission. Unexpected JSON no longer looks like an empty collection.

Run from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python scripts/check_connections.py --tenant sap-dev
```

## Results and next acceptance gate

52 automated tests passed after implementation, including HTTP 401/403/404/429, redirect rejection, malformed collections, OAuth failure short-circuiting and authenticated diagnostics. These use mock SAP transport and are not a tenant certification.

Live read-only checks with the supplied configuration on 2026-09-15 returned HTTP 404 for all five SAP collections. OAuth completed; APIM/AEM remain unconfigured. This supports an endpoint/access diagnosis, not an empty tenant. No writes were attempted.

Next: obtain the correct management API service-key URL; verify operation-specific read access; create one uniquely named DEV package; upload a known-valid test iFlow; approve and deploy; observe runtime STARTED; send a test to its authorized runtime endpoint; correlate a successful MPL entry; save the evidence. Only then expand into APIM mutations, TPM and AEM messaging. Preserve operator approvals for writes and avoid replaying ambiguous prior write attempts.
