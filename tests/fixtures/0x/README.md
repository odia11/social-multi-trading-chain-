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
