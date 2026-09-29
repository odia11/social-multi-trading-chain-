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
bash run-node.sh npm ci --omit=dev --ignore-scripts --no-audit --no-fund
bash run-node.sh test-security.cjs
bash run-node.sh npm audit --omit=dev --audit-level=high
bash run-node.sh read-only-preflight.cjs
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

## Pinned server runtime

Node 18 cannot load the ESM UUID dependency required by rpc-websockets.
All Python builders, installation, audits and preflight now use `run-node.sh`.
The exact Node 22.23.2 release is installed by `deploy/install-pump-runtime.sh`
under `/opt/orcagent-runtime/node-v22.23.2`, owned by root. The official archive
is verified against the committed SHA-256 before extraction. No global Node
replacement, nvm initialization or service sandbox relaxation is required.
The runtime stays outside the app rsync tree and outside ProtectHome.

`.node-version`, package engines and runtime checks enforce the same version.
Direct invocations of every SDK entrypoint reject incompatible runtimes before
loading dependencies. NODE_OPTIONS and NODE_PATH are cleared by the launcher.
For non-production tests, ORCAGENT_PUMP_NODE may identify an absolute path to
the exact same Node release. Missing/wrong runtimes fail closed, never falling
back to PATH. Production uses the installed path without this override.

`deploy/verify-pump.sh ADAPTER [ENV_FILE]` runs the existing bigint checks,
production audit, SDK import and read-only preflight with this launcher. It
reads only SOLANA_RPC_URL from the trusted environment file without printing
its value. No paid transaction is signed or submitted by these checks.

## OrcAgent mint addresses

Every newly prepared mint ends in the case-sensitive Base58 suffix `orc`.
The server generates a random ephemeral mint with solders, before fetching
its recent blockhash, and checks the suffix in both Python and the SDK builder.
The search runs in a lower-priority child process with a 45-second deadline
and a per-service-user nonblocking lock. If it is busy or times out, preparation
fails closed and the user can retry; there is no unbranded fallback.
The temporary lock file contains no key data. Mint secrets travel only over
local subprocess pipes, never API responses, logs, command arguments or storage.
The generated mint signs only its local creation payload; the creator must
still approve in Phantom. The generator never contacts or submits to Solana.
Prepared transactions keep their original mint on retries. Existing tokens,
community-share finalization and reward claims retain their existing addresses.
No wallet address is changed. Uppercase O is not in the Solana Base58 alphabet.

## Recovery of an already submitted launch (no additional transaction)

`Check transaction` and the creator's launch-history page re-verify an existing,
recorded signature. A rate-limited or lagging primary Solana RPC may return 429
or null even after Pump has indexed the mint. Only `getTransaction` and
`getAccountInfo` verification requests may fall back to a fixed mainnet public
RPC. The returned transaction must match the locally stored prepared message
byte-for-byte, verify **every** signature, include the creator fee payer,
matching mint and Pump program, and have no on-chain error. The Pump bonding
curve is checked separately before advancing the status to `live`. The
fallback never creates a mint or supplies an unsigned trading/claim transaction
or blockhash for a paid action. If neither node can verify, the existing
`submitted` record is preserved and another launch must not be attempted.

A confirmed USDC Creator Rewards launch has a wallet-private **Check USDC fees**
read-only button. The displayed Pump creator-vault amount belongs to the
creator wallet **across all its tokens** and is not this token's attributable
revenue or a paid-out balance; separate PumpSwap fees are not included. This
request cannot claim, sign, approve, send, or change the claim ledger. A claim
requires another explicit Phantom approval and its own verified transaction.

The public `/launches` directory lists only confirmed OrcAgent launch records.
Private drafts and unconfirmed signatures never appear there. The global
public launch switch remains OFF until the creator-fee claim route has been
separately tested with explicit user-approved wallet transactions.

## Creator-USDC fee claim pilot — verified read-only preflight

The 100%-Creator / USDC pilot uses `build-reward-claim.cjs`. Its creator wallet
has a **wallet-wide** Pump bonding-curve USDC vault; PumpSwap's separate
creator USDC ATA may also hold fees. The builder checks both exact, derived
accounts via individual `getAccountInfo` calls rather than the Pump SDK's
large supported-quote/indexed `getMultipleAccountsInfo` scans (which some
public RPCs reject with 403). The official Pump SDK still constructs the
claim instruction. A narrowed two-address read shim supplies only the exact
AMM creator vault ATA and recipient ATA the SDK asks for; unexpected keys
fail closed. Nothing in the builder signs or broadcasts.

A fixed public RPC is permitted for **read-only** creator-USDC claim blockhash,
balance, fee, blockhash-validity and simulation requests when the primary RPC
is rate-limited. No launch/signing/sending logic uses this failover. The pilot
still requires a successful simulation and rejects a follow-up estimated SOL
cost greater than 0.005 SOL. Failed preflight stores no claim transaction.

The creator's Phantom wallet must have enough native SOL for its USDC
associated token account rent **if that recipient account does not exist**,
plus Solana transaction fees. OrcAgent cannot pay ATA rent from unclaimed USDC
and never tops up the wallet. In the September 27, 2026 read-only mainnet
check, the creator had 0.000890880 SOL and its canonical USDC ATA was missing:
`simulateTransaction` failed on an account-rent transfer needing 1488440
lamports. These dated amounts are observations, not perpetual balances or a
promise of the next simulation's costs.

The payout ledger has a backward-compatible `received_raw` field. Only after
checking the exact stored Phantom-signed transaction and confirmed on-chain
recipient USDC token balance **delta** does the UI show an actual amount
received. `accrued_raw` remains the earlier, wallet-wide vault observation;
it must never be shown as a payout. An unavailable/malformed receipt fails
closed and can be rechecked from private Claim history. Token Launch remains
restricted to the allowlisted pilot wallet until an owner-approved mainnet
claim is actually signed, broadcast, and independently confirmed.

### A wallet-approved claim can be paid even if the old UI rejects its signature

Phantom's September 2026 iOS `signAndSendTransaction` inserted two standard
ComputeBudget instructions ahead of the intact OrcAgent creator claim and a
bounded pair of wallet-envelope (`L2TEx…`) instructions after it. The old
whole-message equality comparison therefore rejected **already executed**
creator USDC claims. The claim path now checks each ORIGINAL program ID,
ordered account public key and instruction data exactly, all wallet signatures,
matching fee payer and an actual payer SOL debit no greater than 0.005 SOL.
Only the two known compute-budget instructions and the exact two-account
Phantom wrapper are permitted. Unknown instructions are still rejected, and
no tolerance was added to token creation or irreversible fee sharing.

On production startup, a bounded read-only reconciliation examines each recent
pending, submitted or mistakenly expired claim against that WALLET's own
confirmed Solana signatures within the time window of the stored prepared
claim. The exact matching original Pump instructions and verified recipient
USDC token-balance delta are required before the existing record becomes
`confirmed`; an otherwise successful repeated claim with zero received USDC
is instead `confirmed_no_payout` and never presented as a second reward.
Do not ask the wallet to sign again to fix a status mismatch. A claim attempt
with unresolved recent history blocks a second Phantom approval. No raw user
transactions, secrets or external account content are logged by reconciliation.
`tests/test_claim_phantom_wrapper.py` reproduces the wallet envelope and
recovery without mainnet transfers or production DB access.
