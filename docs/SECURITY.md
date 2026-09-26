# Security and operational limits

## Implemented boundaries

- Opaque random bearer tokens map to a tenant, actor and role on the server; browser-supplied tenant claims are not accepted. The viewer role cannot propose; operators cannot approve. MCP should receive operator credentials.
- Every run lookup is filtered by tenant, including decisions, history and recovery. Demo data is tenant-scoped. SAP clients and credentials are separate per configured tenant.
- No production environment is accepted. Configuration is trusted administrator input; the code cannot independently detect a production SAP URL mislabeled DEV.
- No credential enters a plan or prompt. SAP OAuth secrets remain server-side. Extension tokens use `chrome.storage.session`; the browser preview uses sessionStorage. Treat these as development sessions, not hardened enterprise authentication.
- All writes require an immutable plan approval. Hashes bind targets and archive content. There is a metadata drift check, a bounded retry gate and a persistent side-effect journal. No tool can directly invoke a public unapproved write route.
- No cross-origin OData pagination, redirects, arbitrary target URLs, dynamic shell commands, content scripts or remote extension JavaScript. Restrictive manifest permissions and exact optional CORS origin.
- ZIPs have count/size/path/XML checks and are not extracted. Uploading an iFlow can still deploy malicious Groovy, scripts or external connections. Trusted source review is mandatory before approval; this validator is not a code sandbox.
- Timeline rendering uses textContent, never external HTML. SAP error bodies and MPL payloads/attachments are excluded. Plan metadata and MPL summaries may still be sensitive business information.

## Before shared or production hosting

This is a local pilot with a multi-tenant application boundary, not a hardened public SaaS. Do not expose its default local deployment publicly.

1. Replace static bearer keys with OIDC/PKCE, verified issuer/audience, short sessions, explicit tenant membership, revocation and scoped service accounts. Separate proposer/approver duties where required; the local approver can currently propose and approve their own plan.
2. Replace SQLite with PostgreSQL and tenant RLS, a production LangGraph checkpointer, durable job queue, per-tenant/run distributed locks, concurrency quotas, cancellation and idempotency keys at the API boundary. The current process lock requires exactly one worker and does not coordinate replicas.
3. Move secrets to a managed vault/KMS, rotate them, restrict outbound networking to approved SAP hosts, enforce TLS and private ingress. Configured URLs are trusted; there is no DNS rebinding/SSRF defense against a malicious administrator.
4. Encrypt data and backups at rest. ZIP content is currently stored in checkpoint SQLite; do not commit or share `data/`. Define retention, tenant deletion and backup erasure policies.
5. Export approval and execution evidence to an append-only external audit system. Current SQLite evidence is persistent but not tamper-evident or immutable. Duplicate evidence events can occur when replaying a node; operation keys prevent duplicate completed writes.
6. Add audit coverage for every read, request IDs, rate limits, quotas, body/time limits at ingress, dependency scanning, alerting and structured redaction. Application POST body limits do not replace perimeter protections.
7. Add full bundle download/source diff, strong remote revision preconditions, staging and rollback. Current metadata checks have a time-of-check/time-of-use window and do not detect all hidden source changes. Avoid concurrent editing of approved targets.
8. Establish SAP permission matrices and live tenant tests. Test token/CSRF renewal, different API response variants, pagination, upload support and deployment timeouts. A successful runtime smoke check proves neither functional correctness nor absence of downstream side effects.

## Recovery playbook

If the browser disconnects, reopen History. If the server restarts at a pending approval, the checkpoint still waits for that decision. If the process stops during a write, the operation may remain `started`; recovery deliberately stops rather than resending it. Inspect SAP content and task history, record the reconciliation externally, and create a fresh plan only when duplicate effects have been ruled out. Never blindly delete the journal to force a retry.

If polling exhausts its budget, keep reading the original task ID and runtime endpoint. There is no automatic second deployment for an in-progress/unknown build. Failed uploads need a new reviewed plan after remote inspection. No rollback is implemented; do not assume rejection undoes writes already executed.


## Free-model boundary

Only the explicitly submitted goal goes to OpenRouter; SAP credentials, archive bytes, message payloads and automatic inventory are not included. A basic credential-pattern check is implemented, but it is not a comprehensive DLP system: keep secrets out of goals. Both configured keys are used only with catalog-verified `:free` models and a zero-price provider cap. Rate limits produce a shared cooldown. Model output is schema-validated and cannot contain an approval or tenant override. A drafted request still requires a server-generated plan and human approval. The model is not trusted to enforce policy.
