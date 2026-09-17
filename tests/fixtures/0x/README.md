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

## Status: one live quote has been run, and the fixture did not arrive here

A read-only quote was run from the production server and reached the API. The
findings reported back were:

    quoteId_present            false
    allowanceTarget_is_canonical  false
    ephemeral_signer_required  true
    engine_accepts             false

The response file was written on that server and has not been committed, so
this directory still holds no fixture and the parser has still never seen a
real response. Three of those four findings cannot be acted on without it:

  * the ENVELOPE cannot be confirmed without seeing it
  * the allowanceTarget cannot be identified without its ADDRESS
  * the ephemeral-signer flow cannot be built without the FIELD and its shape

What HAS been acted on, because it needed no fixture: the detector behind
`ephemeral_signer_required` had a bug. It answered true for a matching key
merely EXISTING, whatever its value -- so a declared-but-null
`solanaEphemeralSignerPubkey` read as "needs a co-signer". 0x's own EVM ->
Solana example generates no keypair at all, which made a Base -> Solana route
reporting this suspicious. The detector now requires a non-empty value and
reports the field and value it found. Re-running the capture will say whether
that was the cause.

## Getting the fixture here

    # on the production server
    python3 scripts/test_0x_crosschain_quote.py --amount 2 \
        --save-fixture tests/fixtures/0x
    git add tests/fixtures/0x && git commit -m "live 0x fixture" && git push

The script also prints the full sanitized response to stdout now, so pasting
that back works just as well as the file.
