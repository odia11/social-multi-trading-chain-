# Live 0x Cross-Chain responses

Fixtures captured from the real API, so the parser is tested against what 0x
actually returns rather than against what its example code suggests it
returns. Those two were not the same: the integration was written from example
code because `api.0x.org` is unreachable from the build environment, and a
review found several places where it had guessed.

## Capturing one

On a machine that can reach `api.0x.org`, with `ZEROX_API_KEY` set:

    python3 scripts/test_0x_crosschain_quote.py \
        --amount 30 --save-fixture tests/fixtures/0x

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

## Status: real $30 fixtures captured, and what they settled

Two responses from api.0x.org, captured read-only from the production server
on 2026-09-17 for **$30 each**, with the transaction calldata saved at FULL
LENGTH. They replace an earlier pair taken at $2, which is why two different
sets of numbers appear in this repository's history.

### quote_base_to_solana.json — liquidity available, full calldata
The first live evidence this integration has ever had settled three questions,
and all three turned out to be about this repository rather than about 0x:

| First reported | Actually |
|---|---|
| `quoteId_present = false` | quoteId IS present: `0x07dab35a87e2c7dc4f01b20f76f4c808` |
| `allowanceTarget_is_canonical = false` | it IS canonical — AllowanceHolder (Cancun) |
| `ephemeral_signer_required = true` | the field does not appear in the response at all |

* **Envelope** is `quotes`, which is what the parser accepted all along.
  `routes` never appeared.
* **quoteId and zid** are both present and the quoteId is the zid
  (`0x07dab35a87e2c7dc4f01b20f`) plus eight more hex characters. They look
  interchangeable at a glance, which is exactly how `quoteId or zid` came to
  be written and why it was wrong.
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
* **No `simulationIncomplete` field at all** — absent, not `false`. The parser
  reads absent as "not flagged" and sets the route's flag only on an explicit
  `true`.
* **Bridge provider: relay**, ~1 second.
* **Amounts:** sell `30000000`, buy `29744092`, minimum `29446652`.
* **Gas:** `gasCosts` is an object, not a list — `totalNetworkFee`
  `1231589838153` wei at `gasLimit` `148484` and `gasPrice` `8204025`.

**The calldata, read rather than assumed.** 2954 characters, complete, and it
decodes to exactly one thing:

    0x2213bc0b   AllowanceHolder.exec(address,address,uint256,address,bytes)
      operator   0x7d19077317b7574cd01aafa143e5e09f0f4df466
      token      0x833589fcd6edb6e08f4c7c32d4f71b54bda02913   (Base USDC)
      amount     30000000                                      (= sellAmount)
      target     0x7d19077317b7574cd01aafa143e5e09f0f4df466

`exec` pulls `amount` of `token` from the caller, grants `operator` a
TRANSIENT allowance for exactly that, calls `target`, and clears it. So the
blast radius of the whole transaction is (token, amount) — both in plain sight
at the front, both checked against the quote. A route that quotes $30 and
encodes $30000 passes every field-based check and fails this one.

**The economics, at a size a user would actually trade: $0.56 to bridge
$30.00 — 1.87%.** The same route cost 11% of $2. A bridge's costs are largely
fixed, so the percentage is a fact about the SIZE rather than about the route,
which is precisely why `CROSSCHAIN_MAX_BRIDGE_COST_PCT` is a percentage.

### quote_solana_to_base.json — no liquidity
`liquidityAvailable: false`, with a zid (`0x2ec25cea152bdbbe58223a3f`) and
nothing else — at $30 as well as at $2. That is the documented shape of the
discriminated union, not a broken response, and the parser reports it as
`NO_CROSSCHAIN_LIQUIDITY` rather than as malformed or as a fault. Solana ->
Base stays disabled; nothing here is a reason to invent a route.

### A note on the calldata
The earlier $2 captures were saved while the redactor still truncated long
strings, so their transaction `data` read `0x2213bc0b...[2954 chars]` — fine
for checking that the response parses, useless for checking what the
transaction would do. These are saved in full. A truncated calldata is still
REFUSED by the validator, which `tests/test_crosschain_live_base_solana.py`
pins by shortening the real bytes rather than by relying on a fixture that
happens to be short.

A full capture is more useful and no more executable: it is one account's
quote, long expired, and nothing in this repository signs from a fixture.

## Capturing another

    python3 scripts/test_0x_crosschain_quote.py --amount 30 \
        --save-fixture tests/fixtures/0x

Read-only: signs nothing, sends nothing, approves nothing, spends nothing.
The script also prints the sanitized response to stdout (truncated there for
readability; the saved fixture is not).
