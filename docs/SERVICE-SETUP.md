> Update: the new management key passed live DEV acceptance on 2026-09-15. See [current acceptance results](LIVE-ACCEPTANCE-20260915.md). Earlier failures below refer to the previous key or diagnostics.

# Service access needed for live testing

The supplied key authenticates to SAP OAuth, but its runtime URL does not expose management OData collections. A 404 is an endpoint/access failure, not proof that the tenant has no packages. The screenshot shows a trial subaccount and an unrelated stopped app; neither provides management API credentials.

## Cloud Integration

In BTP **Instances and Subscriptions**, locate **Process Integration Runtime** with the **api** plan (not only integration-flow). Use its service key's management `url`, `tokenurl`, `clientid`, and `clientsecret`. Provision the required design-time, deployment, monitoring and Partner Directory roles for the intended tests. Confirm exact role IDs in SAP's current role reference. Copy the management URL into `.tenants.json` with `/api/v1` appended, and update credentials in private `.env`.

Official guide: [Get the Cloud Integration management URL](https://help.sap.com/docs/sap-digital-manufacturing/integration-guide/8c95738469dd4ac78c80e9ca908e0bb3.html). The API-plan key is the source of the URL; do not guess a hostname by editing `-rt`.

## API Management

Requires the **API Portal API access** service plan and appropriate API Portal role. Its service key is separate from the supplied integration runtime key. Add an `apim` object to the SAP tenant:

```json
{
  "api_url": "https://YOUR-API-PORTAL-HOST",
  "token_url": "https://YOUR-APIM-OAUTH-HOST/oauth/token",
  "client_id_env": "APIM_CLIENT_ID",
  "client_secret_env": "APIM_CLIENT_SECRET"
}
```

Set the named environment variables privately and restart. The adapter appends `/apiportal/api/1.0/Management.svc/APIProxies`. Only read-only proxy listing is implemented. No live APIM call was attempted with an unrelated SAP token.

Official reference: [Accessing API Management APIs programmatically](https://help.sap.com/docs/integration-suite/isuite-integrations-and-apis/accessing-api-management-apis-programmatically).

## B2B / Partner Directory versus TPM

The implemented parameter workflow targets Cloud Integration Partner Directory. This can support B2B integrations but does not substitute for Trading Partner Management agreements, partner onboarding, certificate exchange or AS2 message testing. A readable/writable Partner Directory API is needed for parameter tests; a configured TPM tenant and documented API access are required for broader TPM work.

Official reference: [Partner Directory API access](https://help.sap.com/docs/migration-guide-po/migration-guide-for-sap-process-orchestration/accessing-partner-directory-using-api).

## Advanced Event Mesh

Assumption: “AEM” means SAP Integration Suite, Advanced Event Mesh. It requires its console's API base URL and a scoped API token; the Cloud Integration OAuth key does not replace that token. Add an `aem` object:

```json
{"api_url":"https://YOUR-AEM-API-HOST", "api_token_env":"AEM_API_TOKEN"}
```

The adapter reads `/api/v2/missionControl/eventBrokerServices` with the configured token. Creating brokers, queues, subscriptions or publishing/consuming messages is not implemented or verified. Some provisioning may be billable; no service was provisioned in these tests.

Official reference: [Managing AEM services with REST](https://help.pubsub.em.services.cloud.sap/Cloud/ght_use_rest_api_services.htm).

Secrets stay in ignored owner-readable configuration and are excluded from the source ZIP. Because the service/API keys were pasted into the task, rotate them after testing; keep replacement values in local configuration or a secrets manager.

After configuring the missing services, run a read-only check from the repository root:

```sh
PYTHONPATH=backend uv run python scripts/check_connections.py --tenant sap-dev
```

This records diagnostics in `data/connection-check.json` and makes no SAP writes. Once access works, resume acceptance testing with new isolated resource IDs; do not replay the old failed write journal entries blindly.
