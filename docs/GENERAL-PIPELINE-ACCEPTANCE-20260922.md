# General pipeline acceptance — 2026-09-22

The description workflow was changed from a two-template classifier to a typed, composable HTTPS JSON pipeline compiler. Live acceptance created and deployed three new iFlows in SAP package `RelayTest`:

- `RelayFlow61f6e1c9b11d`: invoice collection validation, deduplication, multiplication and conditional routing.
- `RelayFlowa9beadc8d5c4`: inventory mapping, subtraction, filtering and descending sorting.
- `RelayFlowff8375a4d39a`: nested employee-field mapping and case normalization.

All three authenticated runtime calls returned HTTP 200 and exactly matched the output produced by the local specification simulator before deployment. The model calls rotated across both configured OpenRouter key slots and used only catalog-verified zero-price `:free` models.

An unrelated SFTP polling, PGP decryption and S/4HANA OData-write description returned `supported: false`. No run or SAP artifact was created for it. That behavior is deliberate: adding an adapter requires an adapter-specific compiler plus endpoint, authentication and delivery configuration.

Automated coverage is 86 tests. It includes single-object mapping, collection processing, deduplication, calculations, filtering, calculated-field sorting, routing, bundle compilation, deployment-target protection and external-adapter refusal. Machine-readable live evidence is in [general-pipeline-acceptance.json](general-pipeline-acceptance.json).
