# Messaging acceptance — 2026-09-16

Two separate packages were created in the authorized SAP DEV tenant. Verification covers the final JMS worker after its parking-message safeguard was deployed.

## JMS: deployed and live tested

Package `RelayGlobalRetryJMS` contains `RelayJMSIngress` and `RelayJMSWorker`. Both were deployed successfully. The worker uses the shared `Relay_GlobalRetry_Work` queue and routes exhausted messages to `Relay_GlobalRetry_Parking`.

Three authenticated synthetic requests to `/http/relay/retry/submit` returned HTTP 202. SAP message-processing logs and custom properties verified:

- Immediate success: `PROCESSED`.
- Transient failure: `PROCESSED` with `RelayRetryCount=2`.
- Retry exhaustion: `PARKED` after the retry budget.

The parking queue intentionally retains the test messages; no replay consumer or deletion was performed. This is an opt-in retry-envelope pattern. It does not automatically wrap existing tenant integrations. Processing is at least once; downstream idempotency and a real ERP handler remain future work. Malformed-envelope parking was hardened in code but not separately fault-injected in SAP.

## Solace: designs uploaded, connection deferred

Package `RelaySolaceLayeredEDA` contains `RelayEDAExperience`, `RelayEDAProcess` and `RelayEDASystem`. SAP design-time read-back confirmed their externalized configuration keys. Runtime read-back confirmed all three are **NOT_DEPLOYED**, matching the instruction to build first and connect later.

Configure the actual TLS broker host, port, SAP Security Material alias, queues and topic subscriptions before deployment. Placeholder defaults are deliberately nonfunctional. Solace delivery, redelivery and end-to-end business behavior are not yet tested.

## Product verification

- 64 automated backend tests passed; Ruff and extension manifest/UI binding checks passed.
- Browser verification: five generated messaging designs; Solace selects “Upload new iFlow design only”; both live packages and JMS artifacts appear in inventory.
- API contract refreshed with the messaging compile endpoint and upload-only action.
- Chrome side-panel source updated; browser UI checked through the shared local UI. This verification did not repeat native Chrome installation.
- Voice and WhatsApp remain planned channels; see [contracts and roadmap](MESSAGING-AND-VOICE.md).

Machine-readable evidence, including the final test IDs and SAP MPL IDs: [acceptance JSON](messaging-acceptance-20260916.json).
