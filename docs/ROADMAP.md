# Phased product roadmap

Update: free-only goal-to-proposal generation, Partner Directory parameter workflows, capability diagnostics, and read-only APIM/AEM adapters are now implemented. See LIVE-TEST-RESULTS.md for actual verification. Full source generation/repair, TPM business flows, AEM messaging and production SaaS work remain future phases.

## Phase 0 — This local DEV MVP

One installable MV3 side panel, FastAPI, SQLite-checkpointed LangGraph, live/demo SAP tool adapters, isolated configured tenants and human approvals. Support package creation, new exported ZIP artifacts, deployment and read-only verification. MCP clients may discover and propose workflows. Gate to next phase: run the live DEV acceptance checklist in VERIFICATION.md.

## Phase 1 — Reliable SAP DEV pilot

Add enterprise OIDC/PKCE and SAP role tests, full artifact download/source diff, content revision checks, configuration parameter tools, approval expiry, cancellation and operator reconciliation. Move work to a durable queue and PostgreSQL checkpointer, add distributed locking, backups, run-level idempotency and telemetry. Add real HTTP sender tests only for explicitly allowlisted endpoints with approved test payloads and correlation IDs; use a separate runtime invocation service credential. A test must assert expected content/status and correlate its MPL record, not only see STARTED.

Exit: repeatable tenant onboarding, crash/retry drills, exact revision review, functional test evidence and predictable operational limits.

## Phase 2 — Model-assisted generation and safe repair

Add a planner provider (SAP AI Core or another chosen LLM) that produces validated `RunRequest`/capability plans. Keep SAP/tool responses untrusted. Feed a small allowlisted tool catalog and retrieved official examples to the model. Generate iFlows from reviewed templates; validate model, manifest, imports, bindings and scripts before approval. Run generated code/tests in a restricted sandbox. Produce source diffs and test failures for proposed repairs. Every changed artifact or expanded action set must receive a new approval digest.

Bound iteration count, tool budget, time and tenant spend. Evaluate on an offline corpus of representative iFlows, prompt injection attempts and real API failure cases. Do not let a model supply approval or replay unresolved side effects.

Exit: benchmarked success rate on narrow integration families, reviewed changes, constrained repairs, reliable rollback and audit traceability.

## Phase 3 — Multi-tenant SaaS

Tenant self-service provisioning, organization membership, RBAC/ABAC, billing/quotas, KMS-managed per-tenant credentials, region/residency controls and retention policies. PostgreSQL RLS, workload isolation, per-tenant egress, request tracing, durable event streaming, immutable external audit, operational dashboards and SLOs. Make extension sessions short-lived and revocable.

Exit: independent tenant penetration/isolation review, recovery exercises, backups, compliance requirements agreed with pilot customers, metering reconciled with actual tool/model usage.

## Phase 4 — Optional WhatsApp channel

Use Meta WhatsApp Cloud API as a channel adapter into the same run service. Verify webhook challenges and HMAC signatures, deduplicate message IDs, securely link a verified phone identity to organization membership, and enforce conversation/template rules from current Meta documentation. Keep secrets out of messages. Initially support run proposals and status notifications; direct people to the authenticated web/extension review for risky approvals. Obtain explicit opt-in and configure approved templates before sending proactive notifications.

No WhatsApp endpoint, verification bypass, outbound messaging or phone identity mapping exists in this MVP.

## Phase 5 — Capability expansion

- **API Management:** inventory, proxy/spec diff, policy checks, approval-gated deployment and contract tests.
- **B2B / TPM:** partner and agreement metadata, artifact references, bounded onboarding workflows, test messages with traceable correlation; avoid guessing product-specific write APIs.
- **Event Mesh:** namespaces, queues/subscriptions, permission-aware provisioning and safe test events with explicit cleanup.
- **Migration:** inventory/source analysis, compatibility reports, transformation plans, staged tests, transport/rollback and destination environment gates.

Each module implements the capability contract in `modules/`, its own credential scopes and API references, read-only discovery first, typed proposals, exact diffs, policy tests and live acceptance tests. A future UI can select capabilities while preserving the same central approval authority.
