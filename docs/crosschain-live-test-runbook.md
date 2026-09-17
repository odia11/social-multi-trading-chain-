# The controlled live cross-chain test

One real trade, on purpose, with a person watching. This is the step between
"every check we can run offline passes" and "a route is open to users", and it
is the only remaining thing standing in front of Base → Solana.

Everything below is done **on the server**, as the OrcAgent user, with
`ZEROX_API_KEY` set. Nothing below changes what any other user can reach: no
route is written to `/etc/orcagent.env` until the last step, and both scripts
enable a route in their own process only.

---

## What is already proven, and what is not

Offline, against the real $30 capture in `tests/fixtures/0x/`:

| | |
|---|---|
| Parser | quoteId and zid read apart, amounts exact |
| Spender | canonical AllowanceHolder, not the Settler registry |
| Calldata | 2954 real bytes, `exec` pulls 30000000 of Base USDC |
| Simulation | 0x raised no `simulationIncomplete` flag |
| Cost ceiling | $0.56 = 1.87% of $30, under the 5% limit |
| Engine | `verify_route` accepts it; the state machine drives it end to end |

Not proven, and not provable without a wallet:

* **Native gas.** The origin leg is a real Base transaction paid in ETH. 0x's
  estimate for this route was ~0.0000012 ETH; the engine asks for that times
  `CROSSCHAIN_GAS_MARGIN` (1.5). Whether the test account actually holds it is
  a fact about a balance, and preflight says SKIP rather than guessing.
* **That a bridge fills.** That is 0x's and relay's job, and no amount of
  reading a quote establishes it.

Those two are what the live test is for.

---

## Before you start

* A **test account you control** and are willing to lose $30 from. Not a real
  user's account.
* On that account's **Base** address: at least **30 USDC**, plus ETH for gas
  (0.0000018 ETH covers the estimate with margin; a few dollars of ETH is the
  practical answer).
* Its **Solana** address exists — the engine derives it; the bridge delivers
  USDC there.
* A **Solana token mint** to buy with the bridged dollars.
* `ZEROX_API_KEY` in the environment.

Keep `TRADE_ENGINE_CROSSCHAIN=0` and `CROSSCHAIN_ROUTES=` as they are. Neither
script needs them, and turning them on now would open the route to everybody
before it has been watched once.

---

## Step 1 — preflight, with a real wallet

```
python3 scripts/crosschain_preflight.py --amount 30 --wallet <session wallet>
```

Read-only: it asks 0x for a live quote and runs it through every check the
engine would, printing one line per stage. It signs nothing and touches no
key.

The verdict line is the point:

* **READY FOR CONTROLLED LIVE TEST: YES** — every stage passed, including gas
  against the real balance. Go to step 2.
* **NOT PROVEN** — something was skipped. Read which. Without `--wallet` this
  is always GAS, and it is not a pass.
* **NO** — a stage failed, and the line names it. Do not continue. In
  particular:
  * `SPENDER FAIL` — the route nominated a contract that is neither published
    nor pinned. Find out what it is before pinning anything. Never add an
    address to `CROSSCHAIN_ALLOWED_SPENDERS` to make a check go green.
  * `CALLDATA FAIL` — the transaction does not do what the quote says. Stop.
  * `SIMULATION FAIL` — 0x could not dry-run it. Approve the token first, then
    re-quote.
  * `COST LIMIT FAIL` — the bridge costs more than 5% at that size. Quote a
    larger amount; that is the guard working.
  * `GAS FAIL` — the wallet is short of ETH. Top it up.

Note the bridge percentage it prints. It is how you pick the amount for step 2.

---

## Step 2 — one real trade

```
python3 scripts/crosschain_live_test.py \
    --wallet <session wallet> \
    --token  <solana mint> \
    --amount 30 --max-usd 30 \
    --i-understand-this-spends-real-money
```

`--max-usd` defaults to 5 and has to be raised deliberately. On the live
figures a $5 bridge is refused as uneconomical before anything is signed, so
raising it is part of running the test, not a way around a safety check.

The script names the wallet, the balances and the token, then waits for you to
type `yes`. Until then nothing has been sent.

After that it prints every state change as it happens:

```
CREATED → QUOTED → ROUTE_SELECTED → RESERVED → EXECUTING
        → AWAITING_SOURCE → BRIDGING → DEST_RECEIVED → SWAPPING
        → CONFIRMING → COMPLETED
```

**COMPLETED is the answer you want.** With it you get the origin transaction
hash, the bridge's destination hash, the swap hash, and what actually arrived
next to what was quoted.

---

## If it stops halfway

A bridge takes minutes, and the script watching it is not what finishes it.
The trade lives in the database and the reservation stays held;
`_crosschain_resume_loop()` in the running app picks it up every
`CROSSCHAIN_POLL_SECONDS` and carries it to a terminal state — including after
a deploy or a reboot. Closing the script does not abandon the trade.

That worker starts when `TRADE_ENGINE_CROSSCHAIN` is on **or** when the
database still holds an unfinished cross-chain trade — which is exactly this
situation, because the live test runs with the flag off by design. So a
restart of the app during or after the test picks the trade up on its own.
The log line says so:

    [crosschain] resume worker started for 1 unfinished trade(s) even though
    cross-chain is off — money already in flight is finished, not abandoned

To look at one:

```
GET /api/trade/status/<trade_id>
```

or, in the database:

```sql
SELECT state, failure_reason, needs_investigation
  FROM trade_executions WHERE trade_id = ?;
SELECT provider_status, source_tx_hash, destination_tx_hash, swap_tx_hash,
       quoted_out_raw, actual_out_raw, failure_reason
  FROM trade_crosschain WHERE trade_id = ?;
```

What the states mean when it is not moving:

* **BRIDGING** — normal. The origin transaction is on chain and the bridge has
  not filled yet. The resume worker is polling. `CROSSCHAIN_DEADLINE_SECONDS`
  (1 hour, measured from the broadcast and stored, so a restart does not hand
  it a fresh clock) is when it stops counting as slow.
* **REFUND_PENDING** — the bridge failed and the money is expected back. The
  worker watches for it; the claim stays held until it lands.
* **MANUAL_REVIEW** — a person is needed, and the reservation is deliberately
  **still held**. This is what the engine does when it cannot prove what
  happened: a sender that raised after possibly broadcasting, an unknown
  outcome, a second bridge attempt refused. Releasing the claim by hand is how
  a bridged balance gets spent twice; find the origin transaction on Basescan
  first and settle what actually happened before touching anything.
* **FAILED** — nothing was sent, or what was sent reverted before the bridge.
  The claim is released.

Do not re-run the live test against a trade that is still open. The
`trade_crosschain` row is keyed on the trade id precisely so a second bridge
loses at the database rather than in a check somebody forgot.

---

## Step 3 — open the route, and only that route

Only after one trade has been watched to COMPLETED:

```
TRADE_ENGINE_CROSSCHAIN=1
CROSSCHAIN_ROUTES=base->solana
```

in `/etc/orcagent.env`, then restart. Name **one** route. `solana->base` stays
out: its live captures answer `liquidityAvailable: false` at $2 and at $30
alike, and "0x supports the chain" is not the same claim as "we have watched a
trade complete on it".

To close it again, remove the route from `CROSSCHAIN_ROUTES` and restart.
Trades already in flight keep being resumed: the worker starts for unfinished
work whether or not the flag is on, and it picks trades by their own state
rather than by the route. Closing a route stops new trades; it does not
abandon the ones already moving.

---

## What never happens here

* No test is skipped, disabled or loosened to get a green line.
* No spender is pinned to make a check pass.
* The Settler contract is never given an allowance. If a route ever nominates
  one, that is a stop, not a configuration problem.
* Provider calldata is never rebuilt, repaired or shortened. It is verified
  and then signed as sent, or it is refused.
