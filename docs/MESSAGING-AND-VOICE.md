# Messaging scenarios and voice-channel roadmap

## Separate DEV packages

`RelayGlobalRetryJMS` contains:

- `RelayJMSIngress`: authenticated HTTPS `/http/relay/retry/submit` → validate an envelope → Send to `Relay_GlobalRetry_Work` → HTTP 202 acknowledgement.
- `RelayJMSWorker`: JMS sender → inspect `SAPJMSRetries` → retry-budget Router → process, or Send to `Relay_GlobalRetry_Parking` after three retries.

The two queues are dedicated to this prototype. This is a reusable retry-envelope pattern, not an interception mechanism for every existing tenant iFlow. Other producers must opt in to the envelope contract. The prototype processor returns a computed result to its execution log; no downstream ERP operation is implemented. Production use needs a fixed, reviewed handler registry and downstream idempotency, not a caller-controlled URL.

Input example:

```json
{"id":"order-demo-001","payload":{"orderId":"SO-1","amount":25,"quantity":2},"failUntilRetry":0}
```

`failUntilRetry` is a bounded DEV test hook (0–3), used to prove broker redelivery. It is not a production business field. The worker deliberately throws on unsuccessful attempts; it has no success-ending Exception Subprocess that would accidentally acknowledge a failed delivery. After the configured budget, a Send step writes the envelope to the parking queue. If parking fails, the worker fails too so the source message is retried. This is at-least-once processing; downstream idempotency is still required. The parking queue has no automatic replay consumer. Review and explicit replay policy must be added before production use. The JMS adapter's built-in dead-letter feature handles a different class of failures and is not a substitute for application-level retry exhaustion.

`RelaySolaceLayeredEDA` contains three **uploaded, undeployed** designs:

- `RelayEDAExperience`: HTTPS `/http/relay/events/orders` → validate envelope → persistent AMQP publication to `relay/orders/requested/v1`.
- `RelayEDAProcess`: queue `Relay_Order_Process` → validate amount/quantity and calculate total → publish `relay/orders/validated/v1`.
- `RelayEDASystem`: queue `Relay_Order_System` → fulfillment projection → publish `relay/fulfillment/requested/v1`.

The system layer is a projection for a future fulfillment/ERP consumer, not an implemented ERP write. It preserves event ID and uses versioned event types. No broker delivery is claimed until a broker is connected and tested.

Before deployment, configure `SolaceHost`, `SolacePort`, `SolaceCredentialAlias` and each flow's `InputQueue`/`OutputTopic`. Defaults deliberately use `broker.invalid` and `RelaySolaceNotConfigured`. TLS is enabled. The credential value belongs in SAP Security Material; the generated artifacts contain only its alias. Create durable queues and these topic subscriptions on the broker:

- `Relay_Order_Process` subscribes to `relay/orders/requested/v1`.
- `Relay_Order_System` subscribes to `relay/orders/validated/v1`.
- A test/result consumer queue subscribes to `relay/fulfillment/requested/v1`.

Use the actual Solace AMQP TLS endpoint and broker-specific username/VPN convention. An AEM management API token is not a substitute for broker data-plane credentials. Configure broker redelivery limits, dead-message queues, permissions and idempotent consumers before connecting business systems.

## Backend and extension changes

`POST /v1/designs/messaging/compile` accepts `retry_limit` (1–5) and `retry_interval_minutes` (1–60), returns five ZIP artifacts and required configuration. It is operator-only and does not write to SAP. The native side-panel **Messaging patterns** card selects an artifact for plan review.

The new run action `upload` performs approval-gated, new-ID-only design upload and metadata read-back without deployment. Solace uses this path. Existing `upload_deploy` remains available for JMS after capability verification. Upload success does not certify deployability. Existing artifact overwrite is still excluded from the normal UI; this development session's bounded repairs backed up only its own new artifacts and recorded before/after hashes.

## Voice and WhatsApp

Voice capture, local transcription, description-first order design, persistent background approvals and a signed WhatsApp webhook are now implemented. WhatsApp remains disconnected at the user’s request. See [current setup, contracts and limitations](VOICE-WHATSAPP.md).

## References

- [SAP: retry pattern with JMS queues](https://help.sap.com/docs/integration-suite/sap-integration-suite/da17d2d9ef1e4387b31787cd2b454f63.html).
- [SAP: JMS resource APIs](https://help.sap.com/docs/integration-suite/sap-integration-suite/jms-resources-example-requests).
- [SAP: runtime headers including SAPJMSRetries](https://help.sap.com/docs/integration-suite/sap-integration-suite/headers-and-exchange-properties-provided-by-integration-framework).
- [SAP: AMQP sender for Advanced Event Mesh](https://help.sap.com/docs/integration-suite/sap-integration-suite/amq-sender-for-sap-integration-suite-advanced-event-mesh).
- Native AMQP metadata derived from SAP's [integration recipes](https://github.com/SAP/apibusinesshub-integration-recipes) at revision `7005c8cc819c0846c0261cf8246bcacc298da6ee`; license/attribution under `backend/templates/patterns`.
