# Official implementation references

Checked 14 September 2026. These are a curated foundation for this MVP, not an exhaustive inventory. No third-party source code was vendored. Confirm license and NOTICE requirements before copying any future sample.

## SAP samples

- [SAP-samples/ai-enabled-integrations-codejam](https://github.com/SAP-samples/ai-enabled-integrations-codejam): exercises on AI-enabled integration, iFlow generation, MCP exposure/gateway and connecting MCP tools to a client. Useful for the future model/tool integration; it is a workshop rather than a production SaaS runtime.
- [SAP-samples/codejam-code-based-agents](https://github.com/SAP-samples/codejam-code-based-agents): official code-based agent learning material. Useful for SAP deployment and agent ecosystem context. Evaluate deployment patterns independently before applying them to tenant-isolated services.

## API contracts used here

- [SAP Integration Flow Example Requests](https://help.sap.com/docs/integration-suite/sap-integration-suite/integration-flow-example-requests): design-time iFlow operations and base64 bundle content. This MVP implements new artifact upload, not the richer update/configuration surface.
- [SAP Get Runtime Status of Deployed Integration Flow](https://help.sap.com/docs/integration-suite/sap-integration-suite/get-runtime-status-of-deployed-integration-flow): deployment returns a task ID; build status and runtime status are separate observations. The adapter preserves this distinction.
- [SAP Integration Content](https://help.sap.com/docs/integration-suite/sap-integration-suite/integration-content): entry point for content management APIs. Use the API reference matching your service and tenant release to verify authorization and supported requests.

## Runtime and extension

- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts): checkpointed human decisions and resuming via `Command`. Side effects are kept out of the interrupt node before it suspends.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence): durable state/checkpoint concepts, SQLite for local development and PostgreSQL for later deployment.
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk): actual protocol implementation used for tool exposure. This MVP deliberately uses the v1 SDK interface and pins `<2`; the latest major has a different API.
- [Chrome sidePanel reference](https://developer.chrome.com/docs/extensions/reference/api/sidePanel): extension side-panel integration; toolbar-click behavior and the `sidePanel` permission.
- [FastAPI documentation](https://fastapi.tiangolo.com/): Pydantic validation, dependencies and OpenAPI contracts.
- [uv documentation](https://docs.astral.sh/uv/): locked Python environments and repeatable setup.

The latter general documentation links are setup/reference entry points, not evidence of real tenant validation. Future model providers, WhatsApp and new SAP capabilities must be checked against their current official documentation when implemented.
