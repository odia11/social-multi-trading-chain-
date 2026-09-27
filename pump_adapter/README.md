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

## Pilot rollout without enabling public signing

The safe default is `ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED=0`. For the paid
mainnet test, the operator must first obtain the creator's **public** Solana
wallet address, an independently chosen community **public** wallet address,
an exact fee-share split, and a maximum SOL and USDC test budget. No secret
keys, seed phrases, or wallet session tokens are required by OrcAgent.

Only after these parameters are approved, `/etc/orcagent.env` may be configured:

```sh
ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED=0
ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED=1
ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS=<CREATOR_SOLANA_PUBLIC_ADDRESS>
```

For a single-wallet funded pilot, use the root-only helper **after the
budget-guarded commit has been deployed**. It validates the SDK, audited
transitive dependencies and read-only mainnet configuration before changing
any production environment variables, then restarts and health-checks OrcAgent:

```sh
sudo bash ~/orcagent/deploy/creator-pilot.sh YOUR_CREATOR_PUBLIC_SOLANA_WALLET
```

Disable access after the test (or before proceeding if Phantom quotes any cost
above the agreed budget):

```sh
sudo bash ~/orcagent/deploy/creator-pilot.sh --disable
```

The script does NOT sign a transaction and its argument must be a PUBLIC wallet
address, never a secret. The expected full-test budget is 0.03 SOL total and
2 USDC for a **separate manual trade**. The creator launch simulator has a
0.025 SOL pre-approval ceiling, conservatively leaving 0.005 SOL for later
steps. The separate trade is not launched, simulated or debited by this helper:
the user must check its own cost and the cumulative test expenditure before
confirming in Phantom. Network/rent costs can fluctuate and any read-only RPC
failure blocks the pilot rather than silently bypassing its checks.

The existing deployment installer detects an explicitly configured pilot,
installs the pinned SDK, runs the security audit and read-only Pump checks,
and stops the deployment if one fails. Only the exact authenticated creator
wallet can prepare paid transactions; all other users can still save drafts.
The pilot wallet must open the app in a compatible Phantom environment and
approve each transaction. The second transaction for community sharing
allocates the irreversible final split. Do NOT turn on the public global
switch to perform this single-wallet test.

Before a real claim test, eligible on-chain trades must generate creator fees;
creating a coin alone does **not** create an earned-fee balance. Any test buy,
sell, claim or separate SOL-to-USDC swap requires an explicit wallet approval.
Check the actual Pump account state and transaction signatures before
reporting fees received. No transaction amount or network fee is silently
charged to the platform, and estimated vault balances are never booked as
realized revenue. Disable the pilot flag when the test is finished.

### OrcAgent single-creator USDC test (0.03 SOL / 2 USDC)

For an explicitly approved 100% Creator Rewards pilot, deploy the branch and
then configure *one authenticated public Phantom wallet* with:

```sh
sudo bash ~/orcagent/deploy/update.sh
sudo bash ~/orcagent/deploy/creator-pilot.sh PUBLIC_SOLANA_WALLET
```

The pilot script checks the exact deployed version, pinned SDK, npm audit and
read-only Pump configuration before changing the protected service environment.
It sets public launches OFF, private pilot ON, and permits only that creator's
wallet. No community wallet or separate fee-sharing transaction is required.
It never signs or submits a transaction and asks for no secret key. To stop:

```sh
sudo bash ~/orcagent/deploy/creator-pilot.sh --disable
```

Only USDC-quoted 100% Creator Rewards and ONE test token are allowed. The
server rejects an estimated token-creation SOL cost above **0.025 SOL** to
reserve **0.005 SOL** from the approved **0.03 SOL total** test envelope for
follow-up fees. Each claimed creator-fee transaction has its own conservative
0.005 SOL pre-approval limit. The owner must keep an eye on the *combined*
costs across separately approved wallet actions: Token Launch does **not**
control spending in Portfolio/other swap and trading routes. The intended
**2 USDC test trade must be entered and approved separately**; merely
launching a token never initiates that trade. A successful RPC simulation is
not a promise that mainnet fees, rent or price will remain constant.
