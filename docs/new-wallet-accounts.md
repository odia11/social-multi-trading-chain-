# Accounts without a wallet extension

The guest wallet sheet now offers Create new wallet, Connect Phantom, Enter
address (view only), and Import key / sign in. Creation activates a full account
with username/password and an encrypted server trading key. The generated
identity address and trading address are the same; fund that address with SOL
only after activation succeeds.

`new_wallet_accounts.install(dashboard)` is registered in `app_entry.py`, replacing
the legacy onboarding module registration. The old module is retained in source
but its private-key-upload endpoints and assets are no longer installed.
Existing signature and password authentication handlers are unchanged.

## Creation

1. Obtain a guest CSRF token from `GET /api/csrf-token`.
2. `POST /api/account/create-wallet/start` with `X-CSRF-Token`. Returns
   `ok`, `address`, `private_key` (base58 64-byte Solana key), and `token`.
   Every response is no-store. No user or key is persisted by this step.
3. Back up the key, select a unique username (1–20 letters, digits, underscores),
   and a password (at least 10 characters; at most 72 UTF-8 bytes).
4. `POST /api/account/create-wallet/confirm` with the same browser session,
   CSRF header, `token`, `confirmed_backup: true`, `username`, and `password`.
   The server atomically consumes the token before input validation. Any failed
   confirmation requires a fresh wallet/setup; a lost successful response can
   be recovered by signing in with the backed-up key or username/password.

The keypair is stored only in worker memory under a random session-bound token
for ten minutes. A lock serializes claims across threads. Expired records are
pruned on requests and by a daemon cleanup thread. Creation is limited to three
starts per IP per hour, using the deployment's ProxyFix-resolved remote address.
Pending entries are capped at 1,000; active IP buckets at 10,000. Restarting the
worker invalidates unconfirmed wallets and resets these in-memory limits. Keep
gunicorn at one worker; a multi-worker deployment needs a shared pending store.

Confirmation uses `BEGIN IMMEDIATE` and a caller-owned connection to
`get_or_create_user`; existing callers retain their helper's commit/close behavior.
The same wallet-bound double-Fernet helper encrypts the trading key, SHA-256
produces `key_hash`, and bcrypt rounds=12 matches existing password login.
Username uniqueness checks are case-insensitive, matching `/api/username`.
Readonly session data is cleared, CSRF is rotated, and the existing remembered
device helper issues the cookie. Runtime `has_trading_key` becomes true.

Both existing response scanners have an exact-shape, key/address-validated
exception for the intentional start response. No key is logged by this flow.
Other response redaction remains active.

## Import on another device

Import is frontend-only; there is deliberately no `/api/account/import-key`
backend route. Vendored TweetNaCl 1.0.3 signs
`OrcAgent verification\n\nCode: <nonce>` locally and posts only `address`, `nonce`,
and `signature` to the existing `/api/wallet/set`. It never sends the pasted
private key, writes it to browser storage, or replaces a stored trading key.
Import proves ownership for login; a pre-existing external wallet without a
stored trading key still needs the existing trading-wallet setup.

## Validation

```sh
PYTHONPATH=. python -m pytest -q tests/test_new_wallet_accounts.py tests/test_wallet_onboarding.py tests/test_guest_startup_no_legacy_onboarding.py
PYTHONPATH=. python tests/test_trading_wallet_generator.py
PYTHONPATH=. python tests/test_auth_replay_runtime.py
node tests/test_new_wallet_dom.js          # requires jsdom
node tests/test_new_wallet_browser.js      # requires playwright + Chromium
```

Runtime tests use extracted production user/encryption/password/security helpers
without booting scanners or making RPC calls. DOM tests check backup gating,
request fields, key wiping, local signatures and cancellation. The browser suite
also covers desktop/mobile layout and successful reloads. No test submits a live
trade or Solana transaction.
