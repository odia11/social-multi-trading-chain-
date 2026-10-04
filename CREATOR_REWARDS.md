# Creator Rewards pilot

Applications: /creator-rewards. Manual review: /admin/creator-rewards.
Deploying opens applications; creators are not automatically approved.

An approved call creator earns 10% of a qualifying purchase's collected platform
fee. The existing 20% referral share stays separate. Pro discounts apply before
both shares. Trader fees are unchanged.

Call links issue a signed token-specific context valid for 30 minutes. The
context is frozen before execution. Credits require a confirmed/finalized
realized buy, a matching reward_trades row and bundled:<signature> fee receipt.
Self-trades, bot/copy trades, wrong tokens and unsigned/expired contexts do not
earn. Signature and fee ID deduplicate credits. New signature fee receipts also
deduplicate referral accounting. Historical trades are not backfilled.

Review begins after 24 hours. Existing cooldown/reversal eligibility and manual
review determine whether rewards can settle. These controls do not prove that
different wallets have different owners. Pilot membership must remain curated.

## Funded USDC

Current live fees are SOL. The creator's share stays pending in lamports.
An admin converts treasury SOL to USDC outside this feature, then selects pending
rewards and supplies the finalized conversion signature.

Read-only RPC verification requires the fixed fee treasury signer, net SOL/WSOL
spent, USDC received and a receipt dated after the rewards. USDC allocations use
actual received USDC times reward lamports divided by conversion input lamports,
with integer truncation. The network fee is excluded; unrelated SOL debits or
ATA rent conservatively increase conversion input and lower the allocation.
Use clean conversion transactions. A ledger bounds cumulative SOL and USDC
allocations from each receipt. No market-price estimate becomes claimable cash.

Any supported USDC fee remains pending until review and then settles in exact
micro-USDC. This feature does not enable USDC trading or change SOL funding.

## Weekly manual payments

Approved creators request at least 5 USDC. Trade eligibility is rechecked and
eligible available earnings are reserved atomically. One requested payout per
creator is allowed. No transaction is prepared, signed or broadcast.

Admin reviews eligibility, sends the exact reserved amount from the fixed fee
treasury to the displayed account wallet, then records the finalized signature.
The server checks treasury signer, exact recipient USDC credit, treasury debit,
timestamp and unused signature. Only then is the payout marked paid. Conversion
and payout receipts cannot be reused across roles. Actual payment evidence can
still be recorded after a creator is paused, so accounting reflects money that
already left.

Never send again because receipt verification is temporarily unavailable.
Requested funds remain reserved until the receipt can be verified. There is no
automatic payout worker or cancellation/retry transfer path.
Applications, membership decisions, settlement, requests and payments are
audited in creator_audit. All member balances and history are private.

Tests cover money caps, approval, missing receipts, self-trades, review holds,
conversion capacity, payout reservations and recipient proof. Actual Flask
runtime tests use synthetic fills and no real transactions. Browser QA uses
test amounts at 320px, 390px and desktop sizes.
