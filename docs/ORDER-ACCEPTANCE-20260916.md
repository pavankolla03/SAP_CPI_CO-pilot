# Live order iFlow acceptance — 2026-09-16

Package: `RelayAcceptance20260915`. Working artifact: **`RelayOrderBatch20260916V4`**. SAP runtime: **STARTED**. Approved deployment run: `44b78911-fb0b-4d2d-9b65-912e6c71f468`.

Authenticated runtime URL:

```text
https://674521f2trial.it-cpitrial06-rt.cfapps.us10-001.hana.ondemand.com/http/relay/orders/batch20260916
```

## Results

All 10 functional HTTP cases passed against the live SAP DEV runtime:

- mixed routes — HTTP 200, PASS.
- threshold boundary — HTTP 200, PASS.
- malformed JSON — HTTP 400, PASS.
- duplicate ID — HTTP 400, PASS.
- empty batch — HTTP 400, PASS.
- missing ID — HTTP 400, PASS.
- invalid quantity — HTTP 200, PASS.
- 100 orders — HTTP 200, PASS.
- 101 orders — HTTP 400, PASS.
- Per-order exception retains ID and continues to next order — HTTP 200, PASS.

Mixed batch response:

```json
{
  "orders": [
    {
      "id": "ORD-001",
      "status": "ACCEPTED",
      "total": 50
    },
    {
      "id": "ORD-002",
      "status": "REVIEW",
      "total": 1500
    },
    {
      "id": "ORD-003",
      "status": "REJECTED",
      "total": 0
    }
  ],
  "count": 3
}
```

The per-order exception test used a separate synthetic-fault fixture, `RelayOrderExceptionTest20260916`, at `/http/relay/orders/exceptiontest20260916`. Only that fixture deliberately fails ID `TEST-ERROR`; this behavior is absent from the working order pattern. Its response was ACCEPTED → ERROR → ACCEPTED with all three original IDs retained. Message ID: `AGqqLpmW64tmvVvQa4GsSU2qx_6k`.

Main-flow negative cases returned safe HTTP 400 JSON through the batch Exception Subprocess. MPL summaries were read from SAP; handled error responses can still have COMPLETED logs in this tenant, so HTTP/body assertions were checked independently.

The scenario proposal used `nvidia/nemotron-3-super-120b-a12b:free`; OpenRouter reported cost 0. The compiler accepted only validated configuration and generated the fixed program templates.

62 backend tests passed; Ruff, JavaScript syntax, Manifest V3 bindings and permissions checks passed. The native Chrome side panel displayed the generated iFlow inventory. The browser preview compiled the design, displayed its steps, created an approval-gated deployment plan, and rejected that UI-only plan without executing an upload.

## Iteration and retained artifacts

The first order artifact failed model validation. V2 and V3 failed local-route startup. V4 corrected SAP-compatible BPMN ID prefixes and started successfully. A subsequent backed-up repair on V4 corrected validation responses from HTTP 500 to HTTP 400. Earlier failed artifacts were retained for inspection; use **V4**, not the earlier revisions. The backup and detailed repair audit remain under the private ignored `data/` directory. The main product UI still supports new artifact upload only; this session-specific repair was a bounded maintenance operation authorized by the user.

No pre-existing customer iFlows or packages were modified. No external ERP receiver was called. The separate synthetic-fault fixture remains deployed for reproducibility.

[Designer contract and limitations](IFLOW-DESIGNER.md). [Machine-readable evidence](order-acceptance-20260916.json).
