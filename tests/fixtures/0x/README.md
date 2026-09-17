# Live 0x Cross-Chain responses

Fixtures captured from the real API, so the parser is tested against what 0x
actually returns rather than against what its example code suggests it
returns. Those two were not the same: the integration was written from example
code because `api.0x.org` is unreachable from the build environment, and a
review found several places where it had guessed.

## Capturing one

On a machine that can reach `api.0x.org`, with `ZEROX_API_KEY` set:

    python3 scripts/test_0x_crosschain_quote.py \
        --amount 2 --save-fixture tests/fixtures/0x

That asks for a real quote and writes the response here. It signs nothing,
sends nothing, approves nothing and spends nothing, and the response is run
through the same redactor as the printed output.

## What reads them

`tests/test_crosschain_live_fixture.py` picks up every `quote_*.json` in this
directory and runs the real parser over it. With no fixtures present it says
so and passes — an empty directory is an honest "not yet verified", not a
failure. The moment a real one lands, the same test becomes a real check and
will fail if the parser cannot read it.

That is the point: this directory is the seam between "verified against
published example code" and "verified against the live API".

## Status: real fixtures captured, and what they settled

Two responses from api.0x.org, captured read-only from the production server
on 2026-09-17 for $2 each.

### quote_base_to_solana.json — liquidity available
The first live evidence this integration has ever had. It settled three
questions, and all three turned out to be about this repository rather than
about 0x:

| First reported | Actually |
|---|---|
| `quoteId_present = false` | quoteId IS present: `0x7a0f...6f4c808` |
| `allowanceTarget_is_canonical = false` | it IS canonical — AllowanceHolder (Cancun) |
| `ephemeral_signer_required = true` | the field does not appear in the response at all |

* **Envelope** is `quotes`, which is what the parser accepted all along.
  `routes` never appeared.
* **quoteId and zid** are both present and the quoteId is the zid plus eight
  more hex characters. They look interchangeable at a glance, which is
  exactly how `quoteId or zid` came to be written and why it was wrong.
* **allowanceTarget** is `0x0000000000001ff3684f28c67538d4d072c22734` —
  AllowanceHolder for Cancun-hardfork chains, per 0x-settler's own README,
  which lists Base among them. It was ALREADY in the allowlist. Nothing was
  added to make a test pass.
* **The route calls the contract it asks to approve.** That is the
  AllowanceHolder pattern and it is legitimate, but only because this address
  is one 0x publishes. Any other contract doing the same thing is the shape
  of the Settler mistake and is refused.
* **No ephemeral signer**, matching 0x's own EVM -> Solana example, which
  signs with the EVM key alone and creates no Solana keypair.
* **Bridge provider: relay.**

The genuinely new finding is the economics: **$0.22 to bridge $2.00, eleven
percent.** A bridge's costs are largely fixed, so that is a fact about the
size rather than about the route. See `CROSSCHAIN_MAX_BRIDGE_COST_PCT`.

### quote_solana_to_base.json — no liquidity
`liquidityAvailable: false`, with a zid and nothing else. That is the
documented shape of the discriminated union, not a broken response, and the
parser reports it as "no bridge route at this size" rather than as malformed.
Worth re-capturing at a larger amount before concluding anything about the
direction.

### A caveat about the captured calldata
These were saved while the redactor still truncated long strings, so the
transaction `data` field reads `0x2213bc0b...[2954 chars]`. Fine for checking
that the response parses; useless for checking what the transaction would do,
and it could never be broadcast. Fixtures captured from now on keep the
calldata in full — it is not a secret, and it is the thing a parser test most
wants to see.

## Capturing another

    python3 scripts/test_0x_crosschain_quote.py --amount 2 \
        --save-fixture tests/fixtures/0x

Read-only: signs nothing, sends nothing, approves nothing, spends nothing.
The script also prints the full sanitized response to stdout.
