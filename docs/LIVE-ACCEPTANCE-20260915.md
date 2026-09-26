# Live SAP DEV acceptance — 2026-09-15

The new API-plan service key resolved the management endpoint blocker. Package creation, artifact upload, deployment, runtime observation and a real HTTPS message now pass.

- Package: `RelayAcceptance20260915` (Relay Acceptance 2026-09-15).
- Successful iFlow: `RelaySmoke20260915V2`, version 1.0.0, runtime STARTED.
- Final graph run: `d9e36975-993f-4b76-9140-1263b4a8f862`, succeeded.
- HTTPS POST `/http/relay/acceptance/20260915v2`: HTTP 200 with fixed body `{"status":"ok","artifact":"RelaySmoke20260915"}`. The response uses a fixed fixture label; the deployed artifact ID ends in V2.
- Correlated MPL: `AGqpTDRGt-WnaYKOjyn9vN9Ct1Fj`, COMPLETED.
- Chrome: installed Relay side panel listed the real acceptance package and both test iFlows.
- Existing `Shopify_to_S4HANA_Order_Pipeline` was downloaded read-only to inspect artifact structure; it was not modified or redeployed. Test content has no receiver calls or schedules.

## Failures found and fixed

The first test artifact `RelaySmoke20260915` remains in ERROR after an XML-generation failure. A corrected artifact under the V2 ID deployed successfully; failed runs remain in history. An initial V2 run was incorrectly marked needs_attention because the adapter expected mixed-case Success; the live API returned SUCCESS. Case-normalized validation and FAIL handling are now implemented. A subsequent full approved deploy/observe/test/verify/audit run succeeded.

Diagnostic queries were corrected: package reads omit unsupported `$select`, and design-time artifact discovery follows the package navigation rather than the unsupported global collection. All five management preflight checks now pass. With no readable package, the design check is skipped, not called a failure.

The management key returned HTTP 401 when used to invoke the runtime endpoint. The previously supplied runtime key authenticated and delivered the successful message. Credentials remain separate; neither key is included in this evidence or the distributable archives.

54 automated tests pass, including the live-discovered status and query regressions. The direct runtime HTTP test was an acceptance script; the product's generated smoke test remains a read-only runtime assertion. It is not yet a general-purpose business-message runner. APIM/AEM require their own connections and were not tested; full TPM remains unimplemented.
