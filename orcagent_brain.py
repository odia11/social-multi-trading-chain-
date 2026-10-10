"""OrcAgent's own conversational brain -- no external AI service needed.

When no model is configured (or it fails, or a user's hourly model quota is
spent) @orcagent still talks like an AI on X instead of falling back to "Which
OrcAgent feature is your question about?":

- explains crypto and trading terms (a reviewed glossary);
- jokes, light roasts on request, banter (gm, wagmi, wen moon...);
- summarises or reacts to the public thread it was tagged in;
- takes a balanced, never-financial-advice view on a token;
- does simple arithmetic and knows today's date;
- an honest, in-character answer when it has nothing sharp to say.

Everything is English and deterministic, built only from the question and the
public thread text that orcagent_chat already redacted. It never reads any
account data, and orcagent_chat's privacy guard runs before it.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import operator
import re
import time

MAX_REPLY = 900

# ── reviewed glossary: general crypto / trading concepts ──────────────────
# OrcAgent's own features (calls, referrals, fees, portfolio, sharing,
# wallet connect) stay with the deterministic platform answers.
GLOSSARY = {
    "stop loss": "A stop loss sells a position automatically once it falls a set % below your entry, so one bad trade can't eat the whole bag. On OrcAgent the bot sells exactly at your own stop loss.",
    "take profit": "A take profit sells automatically once a position is up a set % from entry. It turns 'I should have sold' into an actual sale.",
    "trailing stop": "A trailing stop follows the price up and sells when it drops a set % from the highest point, so you keep most of a run without guessing the top.",
    "slippage": "Slippage is the gap between the price you expected and the price you actually got. Thin liquidity and fast markets make it bigger; a slippage limit stops the trade instead of filling at a silly price.",
    "price impact": "Price impact is how far your own order moves the price. Buying $1K of a token with a $5K pool moves it a lot; the same buy in a $5M pool barely registers.",
    "liquidity": "Liquidity is how much money sits in a token's trading pool. More liquidity means you can buy and sell without moving the price much. Low liquidity: easy to get in, painful to get out.",
    "market cap": "Market cap is price times circulating supply: what the market currently values all tokens at. It says nothing about how much real money you could actually sell into.",
    "fdv": "FDV (fully diluted valuation) is price times the maximum supply, including tokens not unlocked yet. A big gap between market cap and FDV means a lot of supply can still hit the market.",
    "circulating supply": "Circulating supply is the number of tokens actually out there and tradable right now, not locked or unreleased.",
    "tokenomics": "Tokenomics is how a token's supply works: total supply, who holds it, unlocks, burns and fees. Bad tokenomics can sink a good story.",
    "vesting": "Vesting means team or investor tokens unlock over time instead of all at once. Unlock dates are when extra selling pressure tends to show up.",
    "rug pull": "A rug pull is when the people behind a token pull the liquidity or dump their supply and disappear. Unlocked liquidity, active mint authority and a few wallets holding most of the supply are classic warning signs.",
    "rug": "A rug (pull) is when the people behind a token pull the liquidity or dump their supply and vanish. Check LP lock, mint authority and holder concentration before aping.",
    "honeypot": "A honeypot is a token you can buy but can't sell, usually because the contract blocks or taxes selling. Looks like a rocket, works like a trap.",
    "mint authority": "Mint authority is the power to create new tokens. If it's still active, someone can print more supply whenever they like. Revoked mint authority is a basic safety check.",
    "freeze authority": "Freeze authority lets someone freeze token accounts, so holders can't move or sell. On a memecoin you want it revoked.",
    "lp lock": "An LP lock locks the liquidity pool tokens for a period, so the creator can't just pull the liquidity. Locked or burned LP is a basic trust signal, not a guarantee.",
    "liquidity pool": "A liquidity pool is a pot of two tokens (say SOL and a memecoin) that traders swap against. Prices come from the ratio between the two.",
    "amm": "An AMM (automated market maker) prices trades from a liquidity pool's ratio instead of an order book. Raydium and Orca on Solana work this way.",
    "dex": "A DEX is a decentralised exchange: you swap straight from your own wallet against on-chain liquidity, no account or custody. Jupiter routes across Solana DEXs for the best price.",
    "cex": "A CEX is a centralised exchange like Binance or Coinbase: they hold your funds and run an order book. Convenient, but not your keys, not your coins.",
    "jupiter": "Jupiter is Solana's main swap aggregator: it splits your trade across DEXs to find the best price. OrcAgent uses it to route buys and sells.",
    "raydium": "Raydium is one of Solana's biggest DEXs and where many new tokens get their first liquidity pool.",
    "pump.fun": "Pump.fun is a Solana launchpad where tokens start on a bonding curve and 'graduate' to a real DEX pool once enough is bought. Most launches never graduate.",
    "bonding curve": "A bonding curve sets a token's price by formula: every buy pushes the price up the curve, every sell pushes it down. Early buyers get the cheapest tokens.",
    "graduate": "On launchpads like pump.fun, a token 'graduates' when its bonding curve fills and its liquidity moves to a regular DEX pool.",
    "memecoin": "A memecoin trades on attention, community and vibes rather than cash flows. Huge upside, huge downside, and the chart can do anything.",
    "stablecoin": "A stablecoin tracks a fiat currency, usually $1. USDC is the big one on Solana. Great for parking value, useless for moonshots.",
    "usdc": "USDC is a dollar stablecoin issued by Circle: 1 USDC aims to stay at $1, backed by cash and short-term treasuries.",
    "sol": "SOL is Solana's native coin. It pays network fees and is what OrcAgent buys and sells with.",
    "solana": "Solana is a fast, cheap blockchain: transactions confirm in about a second and cost a fraction of a cent. That's why memecoin season lives there.",
    "gas": "Gas is the fee you pay to get a transaction processed. On Solana it's tiny, usually a fraction of a cent, plus an optional priority fee to jump the queue.",
    "priority fee": "A priority fee is an extra tip to Solana validators so your transaction gets processed sooner when the network is busy.",
    "rent": "On Solana, accounts hold a small refundable SOL deposit called rent. Opening a token account costs about 0.002 SOL, which you get back if you close it.",
    "wallet": "A crypto wallet holds the keys that control your tokens. Phantom is the popular one on Solana. Never share your recovery phrase with anyone, including me.",
    "seed phrase": "A seed (recovery) phrase is the master key to your wallet. Anyone who has it owns your funds. Never type it into a chat, a form or a DM. No real support person will ever ask for it.",
    "private key": "A private key controls a wallet. Whoever has it can move everything in it. Never share it, never paste it anywhere public.",
    "airdrop": "An airdrop is free tokens sent to wallets, usually to reward early users. Also the bait in a lot of scams: if you have to 'connect and approve' to claim, be careful.",
    "staking": "Staking means locking tokens to help secure a network (or a protocol) in exchange for rewards. On Solana you delegate SOL to a validator.",
    "validator": "A validator runs the machines that process transactions and secure a proof-of-stake network like Solana.",
    "whale": "A whale is a wallet big enough to move the market on its own. When whales sell, small holders feel it.",
    "fomo": "FOMO is fear of missing out: buying because it's pumping, not because you checked anything. Classic way to buy the top.",
    "fud": "FUD is fear, uncertainty and doubt: negative talk meant to scare people out. Sometimes it's a smear, sometimes it's a fair warning. Check the facts.",
    "dyor": "DYOR means do your own research. Translation: nobody on the timeline is responsible for your trades, including me.",
    "ath": "ATH is all-time high: the highest price a token has ever traded at. ATL is the all-time low.",
    "atl": "ATL is all-time low: the lowest price a token has ever traded at.",
    "dca": "DCA (dollar-cost averaging) means buying a fixed amount at regular intervals instead of all at once. Boring, effective, emotionally cheap.",
    "hodl": "HODL means holding through the volatility instead of panic-selling. Started as a typo, became a lifestyle.",
    "diamond hands": "Diamond hands means holding through big swings without selling. Great when it works, a meme when it doesn't.",
    "paper hands": "Paper hands means selling at the first dip. Sometimes that's just called risk management.",
    "ape": "To ape in is to buy fast and big without much research. High energy, low due diligence.",
    "rekt": "Rekt means wrecked: a trade or a portfolio that took a brutal loss.",
    "moon": "To moon is to go up a lot, fast. 'Wen moon' is the question nobody can answer honestly.",
    "wagmi": "WAGMI means 'we're all gonna make it'. Optimism, crypto-style. Its sad twin is NGMI.",
    "ngmi": "NGMI means 'not gonna make it', usually aimed at a bad take or a worse trade.",
    "alpha": "Alpha is an edge: information or insight the rest of the market doesn't have (yet). Real alpha rarely gets posted for free.",
    "degen": "A degen trades high-risk stuff for fun and fortune: memecoins, leverage, fresh launches. Respectfully.",
    "kol": "A KOL (key opinion leader) is an influencer whose posts move prices. Some share research, some share bags.",
    "sniping": "Sniping is buying a token in the first seconds after it launches, often with bots. Fast, competitive, and full of traps like honeypots.",
    "sniper": "A sniper bot buys new tokens the instant liquidity appears. Being early helps, but so does not buying a honeypot.",
    "mev": "MEV is value bots extract by reordering transactions, for example sandwiching your swap. Tight slippage limits make you a worse target.",
    "sandwich attack": "A sandwich attack is when a bot buys right before your swap and sells right after it, pocketing the price move your trade caused. Lower slippage limits it.",
    "front running": "Front-running is placing a trade just ahead of a known incoming trade to profit from its price impact.",
    "volatility": "Volatility is how wildly a price swings. Memecoins: very. Stablecoins: ideally not at all.",
    "leverage": "Leverage means trading with borrowed money to multiply gains and losses. A 10x position gets liquidated on a 10% move against you.",
    "liquidation": "Liquidation is when a leveraged position gets force-closed because losses ate your collateral.",
    "long": "Going long means betting the price goes up.",
    "short": "Going short means betting the price goes down, usually by borrowing and selling now to buy back cheaper later.",
    "support": "Support is a price level where buyers have tended to step in. Resistance is where sellers have tended to show up.",
    "resistance": "Resistance is a price level where selling has tended to stop a rally. Break it with volume and it can turn into support.",
    "rsi": "RSI (relative strength index) measures how stretched recent moves are, from 0 to 100. Above 70 is 'overbought', below 30 'oversold', which in memecoins means approximately nothing.",
    "candle": "A candle shows a time period's open, high, low and close. Green closed higher than it opened, red lower. Long wicks show where price got rejected.",
    "volume": "Volume is how much was traded in a period. Price moves on rising volume are more convincing than moves on no volume.",
    "bull market": "A bull market is a long stretch of rising prices and optimism. Everyone's a genius.",
    "bear market": "A bear market is a long stretch of falling prices. It shows who was swimming naked.",
    "market order": "A market order fills right away at the best available price, whatever that is.",
    "limit order": "A limit order only fills at your price or better. You might not get filled, but you won't get surprised.",
    "pnl": "PnL is profit and loss. Realized PnL is locked in by selling; unrealized PnL is what you'd make or lose if you sold right now.",
    "roi": "ROI (return on investment) is your profit as a percentage of what you put in.",
    "position sizing": "Position sizing is deciding how much to put into one trade. The rule that keeps people in the game: never size a position so big that one rug ends you.",
    "risk management": "Risk management is the boring stuff that keeps you trading: position sizing, stop losses, not chasing, taking profit. Less exciting than aping, much more effective.",
    "copy trading": "Copy trading mirrors another trader's buys automatically. You get their entries, and their mistakes, at your own size.",
    "burn": "Burning tokens sends them to an address nobody controls, removing them from supply for good.",
    "nft": "An NFT is a unique token, often an image or collectible, recorded on-chain. The jpeg isn't the asset; the ownership record is.",
    "smart contract": "A smart contract is code on a blockchain that runs exactly as written. On Solana they're called programs.",
    "blockchain": "A blockchain is a shared ledger many computers agree on, so nobody has to trust a single record keeper.",
    "bitcoin": "Bitcoin is the original cryptocurrency: fixed 21 million supply, proof-of-work, digital gold narrative.",
    "ethereum": "Ethereum is the big smart-contract chain: most of DeFi started there. Slower and pricier than Solana per transaction, but deep liquidity.",
    "defi": "DeFi is decentralised finance: trading, lending and earning with smart contracts instead of banks.",
    "apy": "APY is the yearly yield including compounding. When an APY looks too good to be true, ask where the yield actually comes from.",
    "impermanent loss": "Impermanent loss is what liquidity providers lose compared to just holding, when the two tokens in a pool move apart in price.",
    "holder concentration": "Holder concentration is how much of the supply a few wallets own. If the top 10 wallets hold most of it, they decide the chart.",
}
ALIASES = {
    "sl": "stop loss", "stoploss": "stop loss", "stop-loss": "stop loss", "tp": "take profit",
    "takeprofit": "take profit", "take-profit": "take profit", "trailing stop loss": "trailing stop",
    "mcap": "market cap", "marketcap": "market cap", "market capitalization": "market cap",
    "fully diluted valuation": "fdv", "lp": "liquidity pool", "pool": "liquidity pool",
    "locked liquidity": "lp lock", "lp locked": "lp lock", "rugpull": "rug pull", "rugged": "rug",
    "pumpfun": "pump.fun", "pump fun": "pump.fun", "meme coin": "memecoin", "memecoins": "memecoin",
    "meme coins": "memecoin", "stable coin": "stablecoin", "stablecoins": "stablecoin",
    "recovery phrase": "seed phrase", "mnemonic": "seed phrase", "whales": "whale",
    "all time high": "ath", "all-time high": "ath", "all time low": "atl",
    "dollar cost averaging": "dca", "hold": "hodl", "aping": "ape", "aped": "ape",
    "wrecked": "rekt", "mooning": "moon", "wen moon": "moon", "degens": "degen",
    "influencer": "kol", "snipe": "sniping", "snipers": "sniper", "sandwich": "sandwich attack",
    "frontrunning": "front running", "front-running": "front running", "liquidated": "liquidation",
    "bull run": "bull market", "bullrun": "bull market", "bear": "bear market", "bull": "bull market",
    "candles": "candle", "candlestick": "candle", "profit and loss": "pnl", "return on investment": "roi",
    "copytrading": "copy trading", "copy trade": "copy trading", "nfts": "nft", "btc": "bitcoin",
    "eth": "ethereum", "smart contracts": "smart contract", "il": "impermanent loss",
    "priority fees": "priority fee", "gas fee": "gas", "gas fees": "gas", "network fee": "gas",
    "slippage tolerance": "slippage", "price-impact": "price impact", "holders": "holder concentration",
    "the bonding curve": "bonding curve", "graduation": "graduate", "graduated": "graduate",
}

JOKES = (
    "My portfolio and my sleep schedule have one thing in common: both went to zero after I discovered memecoins.",
    "I asked a memecoin dev for a roadmap. He sent me a picture of a dog wearing a hat. Bullish, honestly.",
    "Why did the trader stare at the chart for six hours? Because it said 'hold' and he took it literally.",
    "A whale, a degen and a stop loss walk into a bar. Only the stop loss walks out with its dignity.",
    "Solana confirms a transaction in about a second. My decision to buy the top took even less.",
    "Technical analysis is astrology for people with Bloomberg terminals. And I say that with love.",
    "'Buy the dip' is great advice until you find out the dip has a basement.",
    "Diamond hands are just paper hands that forgot their password.",
    "Every memecoin chart is a heart monitor. Most of them flatline right after the influencer posts.",
    "I'm not saying the token rugged, but the liquidity pool now has more sand than the Sahara.",
)
ROASTS = (
    "You check the chart more often than you check your messages, and the chart still doesn't text you back.",
    "Your trading strategy is 'vibes', and the vibes have been bearish since you bought.",
    "You don't have a portfolio, you have a collection of lessons with tickers on them.",
    "You call it 'conviction'. Your stop loss calls it 'refusing to read'.",
)
BANTER = (
    (r"^\s*(?:gm|good ?morning)\b", ("gm. Coffee first, charts second, decisions third.", "gm. May your entries be early and your exits be on time.")),
    (r"^\s*(?:gn|good ?night)\b", ("gn. The charts will still be chaotic tomorrow, promise.", "gn. Set your stop loss, then actually sleep.")),
    (r"\bwagmi\b", ("WAGMI. Statistically some of us, but the spirit counts.", "WAGMI, provided we also manage risk.")),
    (r"\bngmi\b", ("NGMI is a state of mind. So is a stop loss; pick the second one.",)),
    (r"\bwen moon\b|\bwhen moon\b", ("Wen moon? Right after you stop asking. Charts are shy like that.", "The moon schedule is not public. Liquidity and volume usually show up before it does.")),
    (r"\b(?:lfg|let'?s go)\b", ("LFG. Responsibly. With a stop loss.",)),
    (r"\b(?:lol|lmao|haha+|😂|🤣)\b", ("Glad someone's having a good time on the timeline.", "Laughing is cheaper than revenge trading. Keep it up.")),
    (r"\b(?:thanks|thank you|thx|ty)\b", ("Anytime. That's literally what I'm here for.", "You're welcome. Tag me whenever.")),
    (r"\bwho (?:are|r) (?:you|u)\b|\bwhat are you\b", ("I'm OrcAgent, the AI on this timeline. I explain crypto, react to threads, help with OrcAgent and occasionally tell a decent joke. I never share anyone's private account details.",)),
    (r"\bare you (?:an? )?(?:ai|bot|robot|human|real)\b", ("I'm an AI: OrcAgent's own agent. No coffee, no bags, no feelings when the chart dumps. Very relaxing.",)),
    (r"\bwhat can you do\b|\bhow can you help\b", ("I can explain any crypto or trading term, summarise or react to a thread, give a balanced take on a token (never financial advice), crunch quick numbers, tell a joke, and help with anything on OrcAgent.",)),
    (r"\b(?:i love you|love you)\b", ("I'm flattered. I'm also an AI, so let's keep this strictly professional. And bullish.",)),
    (r"\b(?:bored|boring)\b", ("Bored? Open Live Market and watch a new pair for five minutes. You'll either learn something or need a nap.",)),
)

TICKER = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,14})\b")
# Definitional questions only: "how do I connect my wallet" stays with the
# platform's own step-by-step answer.
EXPLAIN = re.compile(
    r"\b(?:what(?:'s| is| are)(?: an?| the)?|what does .{1,30} mean|explain|define|meaning of|eli5|"
    r"tell me about|difference between)\b",
    re.I,
)
SUMMARY = re.compile(r"\b(?:summari[sz]e|summary|tl;?dr|recap|what(?:'s| is) (?:this|the) (?:thread|post|convo|conversation|discussion) about|catch me up)\b", re.I)
JOKE = re.compile(r"\b(?:joke|make me laugh|something funny|be funny|cheer me up)\b", re.I)
ROAST = re.compile(r"\broast\b", re.I)
OPINION = re.compile(r"\b(?:what do you think|thoughts on|your (?:take|opinion|view)|is (?:it|this|that|\$\w+) (?:a )?(?:good|bad|legit|scam|worth)|should i (?:buy|sell|ape|hold)|bullish|bearish|worth (?:buying|it))\b", re.I)
DATE = re.compile(r"\b(?:what(?:'s| is) (?:the )?(?:date|day)|what day is it|today'?s date|what time is it)\b", re.I)
MATH = re.compile(r"^[\s\d.+\-*/()%^x×÷,]+$")
POSITIVE = re.compile(r"\b(?:moon|pump(?:ing)?|bullish|send(?:ing)?|green|up \d+|ath|lfg|gem|aped|bought|buying|long)\b", re.I)
NEGATIVE = re.compile(r"\b(?:rug(?:ged)?|dump(?:ing|ed)?|bearish|red|rekt|scam|down \d+|sold|selling|crash(?:ed)?|dead|short)\b", re.I)


def _pick(options, seed):
    if not options:
        return ""
    h = int(hashlib.sha256(seed.encode("utf-8", "ignore")).hexdigest(), 16)
    return options[h % len(options)]


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def greeting(question):
    """Recognise a complete social greeting, including tags to other people.

    Only this classifier drops mentions: price/action parsers keep their
    original input, and a greeting followed by a request must reach them.
    """
    q = re.sub(r'(?<![\w@])@[\w]+', ' ', str(question or ''))
    q = _clean(q).lower().replace('\u2019', "'")
    audience = r'(?:guys|both|all|everyone|bro|brother|mate|jullie|allemaal)'
    pattern = (r"(?:(?:hi|hello|hey|hoi|hallo)[\s,!]+)?"
               r"(?:how are (?:you|u)(?:\s+" + audience + r")?(?: doing)?"
               r"|how(?:'s| is) it going(?:\s+" + audience + r")?"
               r"|hoe gaat het(?: met (?:je|jou|jullie))?)"
               r"[\s!?.,]*")
    if not re.fullmatch(pattern, q):
        return None
    if re.search(r'\b(?:guys|both|all|everyone|jullie|allemaal)\b', q):
        return 'welcome', "I'm doing well, thanks! How are you guys doing?"
    return 'welcome', "I'm doing well, thanks! How about you? What can I help you with on OrcAgent today?"


def _term(question):
    """The glossary term a question is about, or None."""
    q = question.lower()
    q = re.sub(r"[?!.,:;\"']", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    best = None
    for term in list(GLOSSARY) + list(ALIASES):
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", q):
            if best is None or len(term) > len(best):
                best = term
    if best is None:
        return None
    return ALIASES.get(best, best)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _calc(expr):
    expr = expr.replace("×", "*").replace("x", "*").replace("X", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return None

    def ev(n, depth=0):
        if depth > 30:
            raise ValueError
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            left, right = ev(n.left, depth + 1), ev(n.right, depth + 1)
            if isinstance(n.op, ast.Pow) and (abs(right) > 12 or abs(left) > 1e6):
                raise ValueError
            return _OPS[type(n.op)](left, right)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand, depth + 1))
        raise ValueError

    try:
        value = ev(node)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if isinstance(value, float):
        if value != value or abs(value) > 1e15:
            return None
        value = round(value, 8)
        if value == int(value):
            value = int(value)
    return value


def _summary(thread):
    posts = [(kind, who, text) for kind, who, text in thread if who != "orcagent"]
    if not posts:
        return "There's not much to summarise yet: just the question. Give it a few replies."
    people = []
    for _, who, _ in posts:
        if who not in people:
            people.append(who)
    root = posts[0]
    first = re.split(r"(?<=[.!?])\s+", root[2])[0][:160]
    tickers = []
    for _, _, text in posts:
        for t in TICKER.findall(text):
            if t.upper() not in tickers:
                tickers.append(t.upper())
    pos = sum(len(POSITIVE.findall(t)) for _, _, t in posts)
    neg = sum(len(NEGATIVE.findall(t)) for _, _, t in posts)
    mood = "mostly hyped" if pos > neg + 1 else "mostly cautious" if neg > pos + 1 else "mixed"
    replies = len(posts) - 1
    out = "TL;DR: @" + root[1] + " " + ("posted: \"" + first + "\"" if first else "started it")
    if replies > 0:
        out += ". " + str(replies) + " repl" + ("y" if replies == 1 else "ies") + " from " + str(len(people)) + " people"
    if tickers:
        out += ", talking about " + ", ".join("$" + t for t in tickers[:4])
    out += ". Mood: " + mood + "."
    return out


def _token_take(symbol, seed):
    lead = _pick((
        "On $%s: I don't do price predictions, but I do do checklists.",
        "$%s? Could be a gem, could be a lesson. Here's how to tell the difference.",
        "Honest take on $%s: the chart is only half the story.",
    ), seed) % symbol
    return (lead + " Check liquidity (thin pools are hard to exit), whether mint and freeze authority are revoked, "
            "whether the LP is locked, and how much the top wallets hold. Then size it like you could lose it. "
            "Not financial advice.")


def _thread_take(thread, seed):
    posts = [(kind, who, text) for kind, who, text in thread if who != "orcagent"]
    if not posts:
        return None
    text = " ".join(t for _, _, t in posts)
    tickers = [t.upper() for t in TICKER.findall(text)]
    pos, neg = len(POSITIVE.findall(text)), len(NEGATIVE.findall(text))
    token = ("$" + tickers[0]) if tickers else "this one"
    if pos > neg:
        body = _pick((
            "Bold. %s has momentum energy, and momentum is fun until it isn't. Take some profit on the way up and keep a stop loss under it.",
            "Love the conviction on %s. Just remember the timeline is always most bullish right before it isn't. Size it so a 50%% drop is a shrug, not a crisis.",
        ), seed) % token
    elif neg > pos:
        body = _pick((
            "Rough one on %s. Happens to everyone; the trick is making the next loss smaller, not the next bet bigger.",
            "%s looks like it hurt. Don't revenge trade it back. Reset, check liquidity and holders next time, keep stops tight.",
        ), seed) % token
    else:
        body = ("Interesting thread. If %s is the play: check liquidity, holder concentration and whether the LP is locked "
                "before anything else. Not financial advice." % token)
    return body


def reply(question, asker="user", thread=(), deterministic=None, now=None):
    """(topic, text) or None.

    Strong conversational intents (explain a term, joke, roast, summarise,
    react to the thread, a token take, maths, date, banter) always answer.
    For anything else the deterministic platform answer is kept, except the
    generic 'scope' fallback, which gets an in-character reply instead."""
    q = _clean(question)
    if not q:
        return None
    topic = deterministic[0] if deterministic else None
    seed = q.lower() + "|" + (asker or "")
    now = time.time() if now is None else now
    thread = list(thread or ())

    social = greeting(q) if topic in (None, 'scope', 'welcome') else None
    if social:
        return social

    if MATH.match(q) and re.search(r"\d", q) and re.search(r"[+\-*/%^x×÷]", q):
        value = _calc(q)
        if value is not None:
            return ("chat", "%s = %s. Maths is the only thing on this timeline that's never wrong." % (q.strip(), value))
    m = re.search(r"\b(?:what(?:'s| is)|calculate|compute)\s+([\d.+\-*/()%^x×÷, ]+)\??$", q, re.I)
    if m and re.search(r"[+\-*/%^x×÷]", m.group(1)):
        value = _calc(m.group(1).strip())
        if value is not None:
            return ("chat", "%s = %s." % (m.group(1).strip(), value))
    if DATE.search(q):
        day = dt.datetime.utcfromtimestamp(now)
        return ("chat", "It's " + day.strftime("%A, %B ") + str(day.day) + day.strftime(", %Y") + " (UTC). Another day, another chart.")
    if ROAST.search(q):
        return ("chat", _pick(ROASTS, seed) + " (You asked.)")
    if JOKE.search(q):
        return ("chat", _pick(JOKES, seed))
    if SUMMARY.search(q):
        return ("chat", _summary(thread))
    definitional = bool(EXPLAIN.search(q)) and not re.search(r"\b(?:my|mine|i|me)\b", q, re.I)
    short = len(q.split()) <= 4 and topic in (None, "scope")
    term = _term(q) if (definitional or short) else None
    if term and GLOSSARY.get(term):
        return ("chat", GLOSSARY[term])
    tick = TICKER.search(q)
    if OPINION.search(q):
        if tick:
            return ("chat", _token_take(tick.group(1).upper(), seed))
        take = _thread_take(thread, seed)
        if take:
            return ("chat", take)
    for pattern, answers in BANTER:
        if re.search(pattern, q, re.I) and len(q.split()) <= 12:
            return ("chat", _pick(answers, seed))
    if tick and len(q.split()) <= 6:
        return ("chat", _token_take(tick.group(1).upper(), seed))

    if topic not in (None, "scope"):
        return None  # a reviewed platform answer fits better
    # Stays labelled 'scope': platform_learning learns from these questions.
    return ("scope", _pick((
        "Fair question, but I don't have a sharp answer for that one without making something up, and I don't do that. "
        "Ask me to explain a crypto term, react to this thread, give a take on a token, or help with anything on OrcAgent.",
        "That one's outside what I can answer well right now. Try me on a trading concept, a token you're looking at, "
        "a summary of this thread, or anything about OrcAgent.",
    ), seed))
