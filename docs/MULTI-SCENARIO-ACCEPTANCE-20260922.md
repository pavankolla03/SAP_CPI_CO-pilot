# Multi-scenario acceptance — 2026-09-22

Package `RelayTest` (`relay test`) was created in the authorized SAP Integration Suite DEV tenant through Relay's approval workflow. Three description-driven iFlows were compiled, uploaded, deployed and invoked through their HTTPS endpoints:

- `RelayOrders5c8b6d4c0861`: batch orders with unique-ID validation, sequential General Splitter, total calculation, Router, Gather and exception subprocesses. The test returned `ACCEPTED`, `REVIEW` and `REJECTED` for the three expected branches.
- `RelayMapd386cbba3125`: required `customer.name` and `customer.email`, returning uppercased `customerName` and lowercased `email`.
- `RelayMapf032ed8bd7c6`: required payment ID, numeric amount and currency, returning a flat normalized payment response.

All endpoint calls returned HTTP 200 with the expected business output. SAP package read-back returned all three artifacts at version `1.0.0`. The machine-readable request/output evidence is in [multi-scenario-acceptance.json](multi-scenario-acceptance.json).

Both configured OpenRouter key slots were used during this acceptance (`1` and `2`). Every reported model was `nvidia/nemotron-3-super-120b-a12b:free`. Relay also verifies the live model catalog reports zero prompt and completion price before any request, rotates configured key slots, applies a shared rate-limit cooldown, and has no paid fallback.

The UI now separates package and iFlow creation in a persistent left navigation. iFlow creation requires an explicit destination package, offers order/mapping examples, displays Relay's interpretation and makes the creation boundary explicit: generation prepares a plan; **Create iFlow & deploy** performs the approved SAP write. The package inventory shows the chosen package and its iFlows.

The compiler boundary remains deliberate. External receivers, ERP writes, arbitrary adapters, schedules, databases and arbitrary generated code are rejected or require clarification. Passing these three scenarios does not claim universal natural-language iFlow generation.
