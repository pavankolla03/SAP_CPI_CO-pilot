# Capability boundary

`capability.py` defines the future discovery/proposal/validation contract. Execution and approval remain centrally owned; future modules must not expose unrestricted writes. The current Cloud Integration adapter is implemented in `backend/app/sap.py`; migration into this protocol is a future refactor, not an active plug-in loader.

Reserve capability names `cloud_integration`, `api_management`, `b2b_tpm`, `event_mesh`, and `migration`. WhatsApp belongs in a future `channels/` adapter because it changes how people communicate, not what tools are authorized. OIDC, billing, organizations, vault storage and provisioning belong in the service layer. No placeholder module is advertised as implemented.
