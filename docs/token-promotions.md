# Paid token promotion

`/promote` provides responsive Basic ($10/24h), Spotlight ($25/24h) and Premium
($50/48h) packages. SOL quotes use the current app SOL/USD price and expire in
10 minutes. Zero/invalid prices fail closed. Network fees are separate.

## Inventory and billing

- Home feed: up to 10 concurrent campaigns, one card after the first eight posts
  (after the last post on shorter feeds).
- Live Market: up to 10 campaigns rotating through three Sponsored cards.
- Premium Home banner: up to five campaigns rotating through one banner.
- Reservations are serialized with SQLite `BEGIN IMMEDIATE`. The scheduler checks
  every interval boundary across all required placements, not only start times.
- Pending quotes hold capacity for 10 minutes. Start/end dates are shown before
  payment. Confirmation starts the full duration no earlier than the promised
  start; late payments get the next available slot.
- Extensions reserve another campaign beginning no earlier than the old expiry.
- At most three open quotes per authenticated wallet reduce unpaid slot hoarding.

Trading-wallet payments reuse the existing native SOL primitive and its durable
request ID. External wallet payments require that quote's payer to sign. All
activation requires a finalized, successful, post-quote-creation system transfer
from that signer to the stored treasury for at least the exact quoted lamports.
A signature is unique across campaigns; legacy payment signatures cannot be
reused. The simulate-confirm endpoint is restricted to demo campaigns owned by the
designated wallet `Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9`.
It cannot activate paid advertising. This wallet can create demo campaigns
without a trading wallet, SOL balance or price quote. Demo campaigns remain
private in My campaigns, spend no SOL and consume no real inventory.

A background sweep reconciles submitted signatures without signing or sending
money. My campaigns also reconciles them. The external-wallet frontend stores a
signed transaction's signature before submitting it to prevent repeated payments
when a confirmation request fails.

## Placement and analytics

Advertising remains separate from market rankings, best calls and trading/bot
entry rules. Ads open `/live-market?mint=<exact mint>`. Names/symbols come from
canonical Solana lookup, and all user content is rendered with DOM text nodes.
HTTPS links are validated; campaigns do not receive verification badges.

Rotation prioritizes fewer measured views plus briefly outstanding deliveries,
with selection counts breaking ties. It pauses in hidden tabs and polls once per
minute. A browser reports a view after at least 50% of a card is visible for one
second. Opaque session-bound receipts deduplicate views and clicks. Unique viewers
are browser-session identities, not verified people. Client telemetry can be
manipulated; it is descriptive analytics, not a billing guarantee.

Campaign owners see views, unique viewers, clicks, CTR, hourly clicks, placement
and timing. The promoted-token directory is searchable and paginated. No audience,
price increase, profit, minimum impressions or trading result is guaranteed.

## Deployment and compatibility

`app_entry.py` installs `token_promotions.py`. Tables are additive. Existing
promotion IDs, payment signatures, remaining durations and placement selections
are copied once from `promotions`; the original table is kept. The legacy Traders
placement is retained in storage but new packages use Home/Live Market only.
Existing market placements appear in the new Sponsored block; legacy Traders-only
purchases do not gain a new placement. That retired legacy surface is not restored.
The old unmeasured Home discovery-rail request is removed.

Deploy through the normal OrcAgent server update procedure and restart the WSGI
process. New quotes and paid campaigns are stored in the new tables, so rolling
back to code that only reads the old table would hide new paid campaigns; prefer
a forward fix while campaigns are running. No on-chain transfer is made during
migration or startup recovery.

## Validation

`python -m pytest -q tests/test_token_promotions.py tests/test_token_promotions_wsgi.py tests/test_native_sol_payments.py`

Covers 50 concurrent reservations, full-interval and multi-placement capacity,
fair rotation, legacy migration, expired quotes, delayed confirmation, ownership,
CSRF, signature replay, exact payment verification, visibility receipt statistics,
native transfer idempotency and installation through the production security stack.
RPC/signing paths are mocked; no live funds are spent.
