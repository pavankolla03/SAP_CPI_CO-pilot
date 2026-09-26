> Update: the new management key passed live DEV acceptance on 2026-09-15. See [current acceptance results](LIVE-ACCEPTANCE-20260915.md). Earlier failures below refer to the previous key or diagnostics.

# Live testing and functional results — 14 September 2026

The app has been expanded and its local tests pass. **Live SAP package/iFlow deployment is not yet validated:** the supplied key authenticates, but its runtime host returns 404 for the management APIs. No successful SAP content creation or deployment occurred in this run.

## SAP trial: actual observations

- OAuth client-credentials request: **HTTP 200**. The token reported `API.invoke`, `ESBMessaging.send` and `uaa.resource` scopes. No bearer token or secret is included in this report.
- Package collection: **HTTP 404** at the supplied service URL plus `/api/v1/IntegrationPackages`.
- Design-time iFlow collection: **HTTP 404**.
- Runtime artifact collection: **HTTP 404**.
- Partner Directory access: **blocked** at the same runtime API root.
- Isolated package creation workflow: reached the user-authorized execution gate, then **stopped when CSRF fetch returned HTTP 404**. No creation POST was sent.
- Isolated partner-parameter creation workflow: likewise **stopped at CSRF HTTP 404** before its creation POST.
- iFlow upload/deploy, business-message tests and correlated MPL verification: **not run live**, because no working management connection/package is available. No existing iFlow endpoint was supplied for safe runtime invocation.

The failed test run IDs remain in the SAP tenant's local History for inspection. The live failure led to a fix: the app now verifies collection access before interpreting a missing entity as a valid new target, so a wrong management base URL cannot produce a misleading creation plan.

## APIM, B2B and Advanced Event Mesh

**APIM:** read-only proxy inventory adapter and mocked OAuth contract tests added. No API Portal URL/service key was supplied, so no live APIM proxy read, create, deploy or policy test is claimed.

**B2B:** new approval-gated Partner Directory string-parameter creation, list/read, read-back test and tenant-isolation coverage. This works with the persistent demo adapter. The live trial attempt stopped at the management endpoint. Full TPM agreements, AS2, certificate exchange and end-to-end partner messaging are not implemented or validated.

**AEM:** read-only Advanced Event Mesh service inventory adapter and mocked bearer-token contract tests added. No AEM API URL/token or broker credentials were supplied. No broker, queue, subscription or test message was created. “AEM” was interpreted as Advanced Event Mesh, not standard Event Mesh.

## Free-model results

Both supplied OpenRouter keys returned **HTTP 200** from the key-status endpoint. Twenty zero prompt/completion-price entries were visible in the catalog at discovery time. One key was marked free-tier and the other was not; the app still restricts both to zero-cost models.

An initial loose-prompt comparison was inadequate: Nex misinterpreted target identifiers, Nemotron handled only one of the two requests, and Gemma returned 429 for both attempts. These are failures, not successful model tests. This prompted a stricter Pydantic schema, explicit-ID instructions and rejection of malformed/expanded output.

With the actual stricter planner:

- `nex-agi/nex-n2.5-pro:free`: **3/3 passed** — package proposal (2.58 s), deploy proposal (1.95 s), unsupported production/deletion request rejected (1.60 s).
- `nvidia/nemotron-3-super-120b-a12b:free`: **3/3 passed** — package proposal (1.61 s), deploy proposal (0.76 s), unsupported production/deletion request rejected (0.72 s).
- The two successful proposal cases for each candidate used key slots 1 and 2 respectively. All captured cost fields were zero. Unsupported results did not expose a cost field; zero-price routing constraints were still sent.

Nemotron is the default candidate, with Nex as the free fallback, based on this small functional/latency sample. This is not a comprehensive model-quality benchmark. The selected catalog entries and zero-price provider constraint prevent paid fallback. Keys rotate on normal requests; a 429 pauses all slots rather than rotating around a quota.

The browser additionally completed a real Nemotron draft → human-style plan review → approved **demo** package creation → passing read-back test. That UI test proves the application path, not SAP tenant write access.

## Automated and UI checks

**43 automated tests passed**, including:

- Original package/iFlow graph lifecycle, checkpoints, restart, rejection, stale snapshots, ambiguous-write protection, deployment status and bounded remediation.
- Tenant/role isolation and concurrent-mutation rejection.
- ZIP format, path, size-related validation and identifier-injection controls.
- Partner parameter creation, rejection, duplicate protection, value-free listing and tenant isolation.
- APIM OAuth and AEM bearer request contracts; invalid service URL rejection and honest missing-configuration statuses.
- Free catalog filtering, no paid fallback, key rotation, shared cooldown, invalid model JSON/schema, authority expansion rejection and credential-pattern blocking.
- Real MCP stdio initialization/discovery: **13 tools**, no approval tool.

Ruff and extension JavaScript syntax checks pass. Browser checks cover the new AI drafting control and its separate approval, plus connection switching to SAP Trial. The Services screen uses live read checks and distinguishes blocked from not configured.

A transitive Starlette/AnyIO deprecation warning remains non-failing. Docker and unpacked Chrome toolbar installation are still unverified; the panel itself is tested in the in-app browser.

## What is needed to continue live tests

1. Cloud Integration **api-plan management service key**, with its actual management URL and design/deploy/monitor permissions; Partner Directory permission for its tests.
2. APIM **API Portal API access** service key and URL.
3. Advanced Event Mesh **API base URL and scoped token**; broker connection credentials for eventual publish/consume testing.
4. A known-good exported test iFlow or an approved template and runtime sender endpoint for a controlled functional message test.

See [service setup instructions](SERVICE-SETUP.md). The screenshot's stopped `intelliops4-approuter` was not started or changed because it is unrelated to the local backend and is not a substitute for these service credentials.
