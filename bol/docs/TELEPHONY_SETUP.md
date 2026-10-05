# Telephony setup — Telnyx / Twilio + LiveKit

Manual dashboard/CLI steps to wire real phone calls into BOL. None of this is
code — it's account setup done once per environment (dev, staging, prod).

BOL is carrier-agnostic by construction: every call — inbound or outbound,
Telnyx or Twilio — terminates in a LiveKit room, and the worker only ever
sees `ctx.room`. It never knows which carrier a call came in on. A
`PhoneNumber` row's own `livekit_trunk_id` (registered in step 3) is what
routes that specific number's outbound calls through its carrier's trunk;
leaving it blank falls back to the platform-wide
`LIVEKIT_SIP_OUTBOUND_TRUNK_ID`. This is what lets Telnyx and Twilio numbers
coexist — each number just points at its own trunk.

Pick one carrier section below (or set up both, if you want numbers on each).

## 1a. Telnyx: get a number and a SIP trunk

1. Create a [Telnyx](https://telnyx.com) account, add a payment method (pay-as-you-go is fine for testing — a few dollars covers weeks of testing).
2. **Buy a phone number**: Numbers → Buy Numbers → pick a number with Voice capability.
3. **Create a Credential Connection** (or IP-based SIP Connection) under Voice → SIP Trunking. This is what LiveKit's SIP bridge will authenticate against for *inbound* calls, and what LiveKit will dial *through* for outbound calls.
4. Note down: the connection's SIP credentials (username/password) and the FQDN Telnyx gives you.
5. Assign your purchased number to this SIP connection (Numbers → your number → Voice Settings → point to the connection).
6. **For call transfers** (`transfer_call` tool): enable SIP REFER on the connection (Voice → SIP Trunking → your connection → look for a "SIP REFER" or "Call Transfer" toggle).

Outbound minutes ~$0.002–0.005/min, inbound ~$0.001–0.0032/min, numbers ~$1/mo. See [docs/RESEARCH.md](RESEARCH.md) for the full cost comparison against Twilio.

## 1b. Twilio: get a number and an Elastic SIP Trunk

1. Create a [Twilio](https://twilio.com) account and add a payment method.
2. **Buy a phone number**: Phone Numbers → Buy a Number → pick one with Voice capability.
3. **Create an Elastic SIP Trunk**: Elastic SIP Trunking → Trunks → Create new Trunk.
4. **Origination** (inbound — Twilio → LiveKit): add an Origination URI pointing at the LiveKit SIP URI shown in your LiveKit Cloud project settings (Settings → SIP).
5. **Termination** (outbound — LiveKit → Twilio): under the trunk's Termination settings, note the Termination SIP URI, and add either an IP Access Control List (LiveKit Cloud's SIP egress IPs) or a Credential List for LiveKit to authenticate with. Use those credentials as `auth_username`/`auth_password` in the outbound trunk JSON below.
6. **Assign your number** to the trunk (trunk → Numbers → add the number you bought).
7. **For call transfers** (`transfer_call` tool): Twilio requires **two** separate toggles on the trunk, not one — Call Transfer (SIP REFER) *and* "Enable PSTN Transfer". Both live under the trunk's settings; miss either one and transfers fail, typically with a SIP 603 response. See [Twilio's SIP REFER call transfer docs](https://www.twilio.com/docs/sip-trunking/call-transfer) for exact menu locations, which shift between Twilio console versions.

## 2. LiveKit: create trunks + dispatch rule

Requires a [LiveKit Cloud](https://cloud.livekit.io) project (or a self-hosted LiveKit + `livekit/sip` — see [self-host SIP docs](https://docs.livekit.io/transport/self-hosting/sip-server/) for the migration path once you're past MVP scale). Use the `lk` CLI ([install docs](https://docs.livekit.io/reference/developer-tools/livekit-cli/)) or the LiveKit dashboard.

The trunk JSON differs slightly per carrier (Telnyx uses a single FQDN +
credential pair for both directions; Twilio has separate
origination/termination). Both produce a LiveKit trunk ID, which is all
BOL ever needs to know about.

### Outbound trunk (BOL dials out)

```bash
lk sip outbound create outbound-trunk.json
```
**Telnyx** `outbound-trunk.json`:
```json
{
  "trunk": {
    "name": "telnyx-outbound",
    "address": "<your-telnyx-fqdn>",
    "numbers": ["+1XXXXXXXXXX"],
    "auth_username": "<telnyx-sip-username>",
    "auth_password": "<telnyx-sip-password>"
  }
}
```
**Twilio** `outbound-trunk.json`:
```json
{
  "trunk": {
    "name": "twilio-outbound",
    "address": "<your-trunk>.pstn.twilio.com",
    "numbers": ["+1YYYYYYYYYY"],
    "auth_username": "<twilio-credential-list-username>",
    "auth_password": "<twilio-credential-list-password>"
  }
}
```

Copy the returned trunk ID into either `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` in
`.env` (if this is your only/default carrier) or the `livekit_trunk_id` field
when registering that specific number in BOL (step 3) — do the latter if
you're running multiple carriers side by side.

### Inbound trunk + dispatch rule (callers reach BOL)

```bash
lk sip inbound create inbound-trunk.json
lk sip dispatch create dispatch-rule.json
```
`inbound-trunk.json` (same shape for either carrier — just the numbers list):
```json
{
  "trunk": {
    "name": "carrier-inbound",
    "numbers": ["+1XXXXXXXXXX"]
  }
}
```
`dispatch-rule.json` — routes every inbound call on this trunk into its own room with the BOL agent explicitly dispatched:
```json
{
  "dispatch_rule": {
    "name": "BOL-inbound",
    "trunk_ids": ["<inbound-trunk-id>"],
    "rule": { "dispatchRuleIndividual": { "roomPrefix": "BOL-inbound-" } },
    "room_config": {
      "agents": [{ "agent_name": "BOL-agent" }]
    }
  }
}
```

Point your carrier's inbound routing at the LiveKit SIP URI shown in your
LiveKit Cloud project settings (Settings → SIP) — for Telnyx that's the SIP
connection's destination; for Twilio that's the trunk's Origination URI (see
1b.4 above).

## 3. Register the number in BOL

Once the DID and trunk are set up, tell BOL about the number, which
carrier it's on, and which agent should answer it. `provider` and
`livekit_trunk_id` are both optional — `provider` defaults to `"telnyx"`,
and an unset `livekit_trunk_id` falls back to the platform-wide
`LIVEKIT_SIP_OUTBOUND_TRUNK_ID`:

```bash
curl -X POST http://localhost:8000/phone_numbers \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "e164": "+1XXXXXXXXXX",
    "provider": "twilio",
    "livekit_trunk_id": "<outbound-trunk-id-from-step-2>",
    "inbound_agent_id": "<agent-uuid>"
  }'
```

Or from the dashboard: Numbers page → "Add a number" — the form has the same
carrier and trunk-ID fields.

## 4. Test

- **Outbound**: `POST /calls/outbound {"agent_id": "...", "to_number": "+1..."}` should ring a real phone within a few seconds.
- **Inbound**: call the number — it should land in a `BOL-inbound-*` room, the worker resolves the called number via `POST /internal/calls/inbound`, and the agent answers.
- **Transfer** (if the agent has `transfer_call` enabled): trigger a transfer mid-call and confirm the callee actually rings. If it fails, it's almost always the SIP REFER / PSTN-transfer toggles from step 1a/1b, not application code.

## Known unverified piece

`worker/agent.py`'s inbound path reads the called/caller numbers off the SIP participant's `attributes` dict using the keys `sip.trunkPhoneNumber` and `sip.phoneNumber`. These follow LiveKit's documented `sip.*` attribute naming convention (confirmed to exist for other keys like `sip.ruleID` in the installed `livekit-agents` source), but were **not** independently verified against a real inbound call in this environment — there was no live SIP trunk to test against, for either carrier. If inbound calls connect but the agent never resolves a call row (check worker logs for "missing sip.trunkPhoneNumber attribute"), check LiveKit's current SIP participant attribute docs and update the two constants at the top of `worker/agent.py`. Verify this once per carrier the first time you take a real inbound call on it — the attribute names are set by LiveKit's SIP bridge, not the carrier, so if it works for one carrier it should work identically for the other, but confirm rather than assume.
