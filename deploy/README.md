# Moving OrcAgent from Railway to your own server

Everything here is meant to be pasted into PuTTY. Work top to bottom.

## Before you start — the two things that can actually cost you

**1. `ENCRYPTION_KEY` must be copied exactly.**
Every user's trading key in the database is encrypted with it. A different
key does not reset anything — it makes every stored wallet permanently
unreadable, and the funds inside them unreachable through this app. Copy the
value from Railway character for character.

**2. Copy the database, or you start empty.**
Users, trades, open positions, calls, posts, fee history — all of it lives in
`orcagent.db`. A fresh install has none of it. Step 4 covers this, and does it
in an order where a mistake costs you nothing.

Also worth knowing: while both are running, **two copies of the bot are live
on the same wallets**. Do the cutover in one sitting and stop Railway as soon
as the new server answers (step 7).

---

## 1. Get the code onto the server

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/odia11/social-multi-trading-chain-.git ~/orcagent
cd ~/orcagent
```

Clone it as your own user, not root: you will be running `git pull` here on
every deploy, and needing `sudo` for that is friction you would feel weekly.

The location itself does not matter — only that it is **not** `/opt/orcagent`.
That directory is a copy the installer overwrites from this clone, so edits
made there are erased on the next deploy.

## 2. Run the installer

```bash
sudo bash deploy/install.sh
```

Installs Python, nginx and sqlite, creates a locked-down `orcagent` service
user, builds the virtualenv, and installs the systemd service and nginx site.
It does not write any secret and does not touch any database.

## 3. Fill in your secrets

```bash
sudo nano /etc/orcagent.env
```

Every value comes from Railway → your service → **Variables**. Click the eye
icon to reveal each one. `ENCRYPTION_KEY` first, and check it twice.

## 4. Bring your live database across

On Railway, open a shell to your service (Railway → your service → the `⋮`
menu → **Shell**) and check where the data actually is:

```bash
ls -la /data
```

Download `orcagent.db` from there. If Railway's UI has no download, print it
as base64 and copy the text out:

```bash
base64 /data/orcagent.db
```

Then on your server, paste it back:

```bash
sudo systemctl stop orcagent            # nothing should be writing during the copy
cat > /tmp/db.b64                       # paste, then press Ctrl-D
sudo base64 -d /tmp/db.b64 > /data/orcagent.db.new

# Only replace the live file once the copy proves to be a valid database.
sudo sqlite3 /data/orcagent.db.new "PRAGMA integrity_check;"    # must print: ok
sudo sqlite3 /data/orcagent.db.new "SELECT COUNT(*) FROM users;"  # must look right

sudo mv /data/orcagent.db.new /data/orcagent.db
sudo chown orcagent:orcagent /data/orcagent.db
rm /tmp/db.b64
```

The check before the `mv` is the point: a truncated paste is caught while the
old file is still untouched.

## 5. Start it

```bash
sudo systemctl start orcagent orcagent-monitor
sudo systemctl status orcagent
sudo journalctl -u orcagent -f
```

(`orcagent-monitor` is the Telegram uptime alerter. It stays silent unless
you filled in `TELEGRAM_BOT_TOKEN`.)

In the log you should see the startup lines this app prints about itself:

```
[startup] ENCRYPTION_KEY fingerprint: ab12cd34 (sha256 prefix — not the key itself)
[startup] owner wallets (full admin rights): Cdn8Wfta…
[startup] gas sponsor wallet (EVM): 0x9adAd542…
[startup] gas sponsor wallet (Solana): 9zdKtt8p…
```

**Compare that `ENCRYPTION_KEY fingerprint` with the one in your Railway
logs.** Same fingerprint means the key came across correctly and every stored
wallet still decrypts. Different means stop and fix it before anyone trades.

Check it answers:

```bash
curl -s localhost:8080/health
```

## 6. Point the domain here and switch on HTTPS

At your DNS provider, point `orcagent.fun` and `www` at this server's IP
(an `A` record each). Wait until `ping orcagent.fun` shows the new IP, then:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d orcagent.fun -d www.orcagent.fun
```

Certbot edits the nginx site for you and sets up automatic renewal.

## 7. Stop Railway

Only once the new server serves the site over HTTPS: in Railway, remove the
domain and pause or delete the service. Until you do, both copies of the bot
are trading the same wallets.

Also update anything that points at the old host — the callback URL in the X
Developer Portal has to match your domain exactly.

---

## Check that the outside world is actually reachable

```bash
sudo bash -c 'set -a; . /etc/orcagent.env; set +a; cd /opt/orcagent && \
  PYTHONDONTWRITEBYTECODE=1 venv/bin/python tools/verify_live.py'
```

(The whole thing runs under `sudo` because `/etc/orcagent.env` is readable
only by root and the service user. Reading it in a `$( )` first would be
expanded by your own shell, which cannot open it.)

Run this after the first start, and after any change to keys or networking.
It calls 0x, Jupiter, DexScreener and every chain's RPC with your real keys,
prices a real $100 trade, and checks that its parts add up to $100 rather
than $100.75.

It is read-only — it quotes and reads balances, signs nothing, sends nothing,
and prints no key. Exit code 0 means everything the app trades through is
reachable from this server.

This matters more than it sounds. The development environment has no route to
any of those services, so none of the trading adapters has ever run against a
live API. Until this passes here, that part of the app is untested rather
than tested.

## Running it day to day

```bash
sudo systemctl restart orcagent orcagent-monitor   # restart
sudo journalctl -u orcagent -f                     # follow the logs
sudo journalctl -u orcagent --since "1 hour ago" | grep -i error
```

Deploy a new version:

```bash
cd ~/orcagent && git pull            # wherever you cloned it -- NOT /opt/orcagent,
                                     # which install.sh overwrites from the clone
sudo bash deploy/install.sh          # safe to re-run; leaves /etc/orcagent.env, /data
                                     # and certbot's nginx config alone
sudo systemctl restart orcagent orcagent-monitor
```

Back up the database — on a schedule, and by hand before any deploy that
touches storage:

```bash
sudo sqlite3 /data/orcagent.db ".backup /data/backups/orcagent-$(date +%F-%H%M).db"
```

`.backup` is used rather than `cp` because it takes a consistent snapshot
while the app is still writing.

The app keeps three compressed copies of its own in `/data/backups`. That
protects you from a bad write. It does not protect you from losing the
server, so copy that directory somewhere else too.

---

## Two notes on how this is set up

**One worker, deliberately.** The trading bot, the bridge poller, the gas
manager and the surge radar all run inside the web process. A second worker
is a second copy of all of it — two processes buying the same token, two gas
grants for one empty wallet. `deploy/orcagent.service` pins it to one worker
with four threads; please don't raise it.

There is now a second reason. The guards that stop a double-click becoming
two buys or two sells are in-process locks: a second worker holds its own
copy, and the second click gets through. Threads are fine — they share the
locks — but workers are not. If the app ever has to scale past one, those
guards need to become database claims first, the way the EVM buy's balance
reservation already is.

**Data lives in `/data`, code in `/opt/orcagent`.** The app reads `DATA_DIR`
first and otherwise switches to `/data` automatically when that directory
exists. Keeping them apart is what
makes redeploying safe: `install.sh` replaces the code and never reaches into
your database.
