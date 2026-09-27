# Provider-confirmation evidence (not sent externally)

The client tested `POST https://api.scaledown.xyz/v1/scaledown`, requested model
`classify-1`, identical `state.text` and choice questions, with the **top-level**
`"reasoning": false` versus `"reasoning": true`.

Both were HTTP 200. Across 657 paired warm trials, neither variant returned any
field named reasoning, and every pair reported identical `usage.output_tokens`.
Mean false−true latency was −1.4ms (family bootstrap95% −8.8 to +5.5ms). Full
actual requests, responses, timestamps and hashes are in measurements evidence.

Please confirm for this account and endpoint:

1. Is `reasoning` a top-level request field on `/v1/scaledown`, or is the quoted
   classify API a different endpoint/schema?
2. Should true return reasoning in this response format? Is it intentionally
   hidden or unsupported in this compatibility endpoint?
3. Is dedicated routing active for this endpoint/model/key? A response model name
   of `classify-1` alone does not identify the serving backend revision.

No API key is included. No Slack/email message was sent as part of the work.
