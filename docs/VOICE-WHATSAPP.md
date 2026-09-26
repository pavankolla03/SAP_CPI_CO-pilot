# Voice, descriptions and WhatsApp

## Working locally

The side panel now records or accepts audio (60 seconds, 5 MB maximum). The backend decodes and transcribes it with a local multilingual faster-whisper model. Review the transcript, then choose **Use as order scenario** and **Create order iFlow from description**. That button uses the selected existing package or the server-owned tenant `description_package_id`, generates a unique iFlow ID and HTTPS path, interprets the description with the existing free-only planner, compiles the native design and creates an approval plan. No SAP write occurs before approval.

Supported description-first behavior includes the **batch-orders pattern** (HTTPS JSON orders, unique-ID validation, General Splitter, amount × quantity, Router, Gather and Exception Subprocesses) and scalar **JSON validation/mapping** (dot-path input, flat output and bounded transforms). It does not implement arbitrary ERP receivers, persistence or every SAP adapter. Unsupported scenarios return clarification instead of a fabricated implementation.

Choose **Execute approvals in the background** before approving to enqueue a persistent job. The backend must stay running, but the panel can close. Activity → Channel jobs exposes progress and links to the full run. The existing foreground approval path remains available. Neither mode is an unattended production autopilot.

```sh
uv sync --extra voice
uv run --extra voice python scripts/setup_voice.py
```

Set `VOICE_ENABLED=true` and `VOICE_MODEL_PATH=data/voice-model`. Model installation is a one-time download; inference uses local files only. Recording requests microphone permission on user action. If Chrome disallows recording in a particular panel context, upload a recording instead. Closing the panel stops microphone tracks. No browser/remote speech-recognition service is used. Audio is held in memory, not saved by the application. Transcripts used in plans are retained in the run audit; avoid dictating secrets. Only scenario text, never audio or SAP credentials, goes to the free-model planner.

## WhatsApp: implemented and locally tested; account connection deferred

The Cloud API webhook is disabled by default, and no real WhatsApp message has been sent. Enable only after account setup and recipient linking:

- `WHATSAPP_ENABLED=true`
- `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_GRAPH_VERSION=v25.0` (verify the version supported by your Meta app)
- `WHATSAPP_LINKS_JSON`: map allowed sender numbers in international digits-only format to `{tenant_id, actor, role}`. These are administrator-owned claims; never accept tenant/role claims from a message.
- `WHATSAPP_SEND_ENABLED=true` only when replies to those linked recipients are intended.

Serve `/webhooks/whatsapp` through a trusted HTTPS gateway and configure Meta's messages subscription. GET answers the verification challenge. POST verifies `X-Hub-Signature-256` over the exact raw bytes, checks the receiving phone-number ID and sender link, then queues the message. Unknown senders are ignored. IDs are deduplicated persistently. The MVP accepts messages less than one hour old and limits each linked identity to ten newly queued messages per minute. Replies expire after 23 hours in the queue; templates for delayed notifications are not implemented. Status-only events are acknowledged and ignored.

Supported messages:

```text
HELP
BUILD: Receive multiple orders over HTTPS, split by ID, calculate total, route high values for review and handle exceptions.
/package DemoOrders Demo Orders
/deploy DemoOrders ExistingFlow
/orders DemoOrders NewFlow /relay/new-orders Receive and route batch orders with exception handling.
STATUS <run-id>
APPROVE <run-id> <exact-plan-hash>
REJECT <run-id> <exact-plan-hash>
```

`BUILD:` uses the tenant's default package and generated artifact IDs. `/orders` preserves explicit IDs and path. Natural-language package/deployment requests use the constrained free planner and require explicit targets. Audio notes use the same commands after transcription, but **audio cannot approve or reject a plan**. Plans can also be reviewed in the side panel. WhatsApp approvals must come from a linked approver and can access only runs created through that linked identity's channel jobs.

Media is fetched with the server token from Meta's media API; its returned download URL must be HTTPS on `lookaside.fbsbx.com`, with redirects disabled and a streamed size cap. No user-supplied URL is fetched. Provider failures stop the job; no paid transcription fallback exists.

## Worker, retention and deployment constraints

This release runs one API process with one channel worker thread and SQLite. Queued work survives a restart. Jobs interrupted during processing become `needs_attention`, and are not automatically replayed. Inspect the run audit before resubmitting. Outbound requests with ambiguous delivery become `uncertain` and are never blindly resent. `sent` means Meta accepted the request, not confirmed phone delivery. Phone links are checked again before processing/sending.

Completed inbox payloads are cleared. Run audits, message IDs, sender identifiers, timestamps and results remain in the private database; production retention/deletion policies are still required. Do not share the data directory. A production installation also needs secret management, webhook ingress limits, verified identity enrollment, worker isolation, delivery receipts, observability and a database/job-queue migration before multiple API workers are used. No public tunnel or Meta account was provisioned by this implementation.

## API contracts

- `POST /v1/voice/transcribe`: operator bearer authentication; raw `audio/*` body; returns editable text, language, duration and `review_required`.
- `POST /v1/scenarios/orders`: operator; `{description, package_id?}`; returns clarification or compiled design details and an awaiting-approval run.
- `GET /v1/channels`: authenticated configuration/readiness flags, no secrets.
- `GET /v1/channel-jobs`: current tenant and actor only.
- `POST /v1/channel-jobs/decision`: approver; `{run_id, approve, plan_hash}`; returns HTTP 202 and persistent job ID. Repeated submission deduplicates the same decision.
- `GET/POST /webhooks/whatsapp`: Meta verification/signature authentication, independent of Relay bearer tokens.

## Validation

78 automated tests pass, including signature rejection, duplicate delivery, tenant isolation, voice approval rejection, background decisions, interrupted-job recovery, media-host protection and ambiguous reply handling. Real local speech transcription plus free-model interpretation and approved background SAP deployment were verified on 2026-09-21. The deployed flow processed a three-order test with ACCEPTED, REVIEW and REJECTED results. See `description-voice-acceptance.json` for IDs and evidence. Microphone permission UX and actual WhatsApp delivery still require testing on the user's chosen device/account.

Sources: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Meta webhook verification](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/), [Meta media API collection](https://www.postman.com/meta/whatsapp-business-platform/request/fpj02x0/retrieve-media-url).
