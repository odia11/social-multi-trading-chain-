# OrcAgent Pump Token Launch — isolated adapter

The Flask app stores token launch drafts and statuses. These Node helpers build
Pump SDK **transactions for the creator to review and sign in Phantom**. They
never hold the creator's private key and never send a transaction themselves.
Token launch and reward claims remain disabled by default until an authorized
mainnet release sets `ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED=1`. Merely deploying
this adapter, running tests or a read-only preflight moves **no funds**.

## Reproducible security controls

The official `@pump-fun/pump-sdk` is pinned to `2.0.0` in `package-lock.json`.
The SDK still depends on `@solana/buffer-layout-utils` and deprecated
`bigint-buffer` 1.1.5, whose optional C addon has a known buffer overflow.
The OrcAgent runtime instead resolves **all imports** of `bigint-buffer` to
`vendor/bigint-buffer-safe` 1.1.6, a tiny, native-free replacement supporting
only the four conversion helpers used by the Solana SDK. Its maximum binary
size is 65,536 bytes and invalid/overflowing values throw. The `npm ci`
installation also uses `--ignore-scripts`, so no native addon can be compiled.
The local fork is not an upstream release; review and retest it on every SDK
upgrade.

Known patched transitive packages are pinned by npm overrides (TOML,
stream-json, and `jayson`'s UUID). `npm audit` is an **advisory snapshot**, not a
security guarantee or proof of real transaction execution.

Run from `pump_adapter`:

```sh
npm ci --omit=dev --ignore-scripts --no-audit --no-fund
node test-security.cjs
npm audit --omit=dev --audit-level=high
node read-only-preflight.cjs
```

The last command checks the current Pump mainnet configuration and builds
USDC/SOL creator, community and holder transactions with throwaway keys. It
performs **read-only RPC calls only**; it does not create a token, distribute
creator fees, spend SOL, or validate end-to-end mainnet settlement. Use a
trusted HTTPS Solana endpoint via `ORCA_LAUNCH_RPC` when public RPC is rate
limited; never paste a secret key into this variable.

## Rollout

1. Deploy with the feature disabled (default), so drafts and metadata work but
   neither token signing nor claims can be prepared.
2. Run the offline Flask tests and above SDK checks. Production install
   automatically gates an explicitly enabled feature on these SDK checks.
3. Do a separately approved, small **funded creator-wallet mainnet test**:
   create USDC-paired token, verify exact wallet-signed transaction and quote
   mint; finalize community shares with another wallet approval; validate the
   immutable on-chain recipients/basis points; then verify actual creator fee
   deposits and claims. Also test a SOL-quoted launch and the separate,
   wallet-authorized SOL->USDC conversion.
4. Enable the feature only after the results are reviewed. Do not treat a
   successful read-only preflight as a live-value test.

OrcAgent charges no extra Token Launch fee in this release. Actual Pump
creator fees do not equal OrcAgent's existing trade fee, and a reward claim is
not itself a second revenue event. Holder Rewards are handled by Pump, not by
an OrcAgent creator claim.
