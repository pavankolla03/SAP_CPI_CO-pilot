# Relay extension UI 0.3

The UI is an original dark charcoal and navy side panel with pale lime accents and locally bundled Manrope typography. It uses the focused conversation-to-plan interaction requested from the competitor reference while retaining Relay branding, code and security boundaries. No third-party site assets or branding are bundled.

## Included

Manifest V3 side panel; toolbar launch; Command+Shift+Y on Mac and Ctrl+Shift+Y elsewhere; extension icons; setup guide; Describe, Plan, Diagram and Deploy steps; Packages, Activity and Connections views; requirement evidence; architecture flow cards; clarification and blocker display; exact BPMN rendering; immutable plan/diff and execution timeline; retained approval controls.

## Verification — 2026-09-25

- Browser preview inspected in the narrow side-panel layout with no horizontal overflow.
- The full Describe → Plan → Diagram → Deploy route was exercised against the running backend. The final product-routing run is intentionally awaiting approval because no acceptance sample was supplied.
- `node scripts/check_extension.mjs` checks manifest paths, permissions, shortcut, DOM bindings and toolbar behavior with a Chrome API mock.
- The full backend suite passes 100 tests, including frozen-plan idempotency, tenant isolation, requirement omissions, unsupported adapters and acceptance mismatches.
- Two generated designs were approved, deployed and invoked on the configured SAP Trial DEV tenant. Shipment routing and customer normalization returned the exact expected JSON; malformed JSON returned HTTP 400. Evidence is in `solution-workspace-acceptance.json`.
- The source and extension ZIP are ready for **Load unpacked**. Public Web Store publishing and automatic Chrome installation are outside this local build.

## Install

Extract `relay-chrome-extension.zip`, open Chrome extensions, enable Developer mode, choose Load unpacked and select the extracted `extension` folder. Keep the backend running and follow the built-in Extension guide.
