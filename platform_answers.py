"""Specific, reviewed English product answers. No model calls or invented account facts."""
import re

HOME = 'https://orcagent.fun/#app-home'
MARKET = 'https://orcagent.fun/live-market'
PORTFOLIO = 'https://orcagent.fun/#app-portfolio'

ACTION_REQUEST = re.compile(
    r"\b(?:can|could|would|will)\s+(?:you|u)\b|"
    r"\b(?:do|handle|make|place)\s+(?:it|this|the\s+(?:buy|sell|trade))\s+for\s+me\b|"
    r"\bfor\s+me\b|"
    r"\b(?:kun|kan|wil|zou)\s+(?:je|jij|u)\b|"
    r"\bvoor\s+mij\b",
    re.I,
)
INSTRUCTION_REQUEST = re.compile(
    r"\b(?:tell|show|explain|teach|walk)(?:\s+me)?\b.{0,50}\b(?:how|where|steps?)\b|"
    r"\bhow\s+(?:do|can|should)\s+i\b|"
    r"\b(?:kun|kan)\s+je\s+(?:me|mij)\s+(?:uitleggen|vertellen|laten\s+zien)\b|"
    r"\bhoe\s+(?:kan|moet)\s+ik\b",
    re.I,
)
BUY_WORD = re.compile(r"\b(?:buy|buying|purchase|kopen|koop)\b", re.I)
SELL_WORD = re.compile(r"\b(?:sell|selling|verkopen|verkoop)\b", re.I)
TRANSFER_WORD = re.compile(r"\b(?:send|transfer|stuur|verstuur|overmaken)\b", re.I)
TIP_WORD = re.compile(r"\b(?:tip|tippen|fooi)\b", re.I)


def _amount_named(text, unit, maximum):
    m = re.search(
        r"(?<![\w.])(?:\$)?(\d{1,9}(?:[.,]\d{1,9})?)\s*" + re.escape(unit) + r"\b",
        text,
        re.I,
    )
    if not m:
        return None
    value = m.group(1).replace(",", ".")
    try:
        number = float(value)
    except ValueError:
        return None
    if not (0 < number <= maximum):
        return None
    return ("%f" % number).rstrip("0").rstrip(".")


def _amount_sol(text):
    return _amount_named(text, "SOL", 500)


def _amount_usdc(text):
    return _amount_named(text, "USDC", 100000000)


def _token_symbol(text):
    m = re.search(r"\$([A-Za-z][A-Za-z0-9_]{1,19})\b", text)
    if m:
        return m.group(1).upper()
    m = re.search(
        r"\b(?:buy|purchase|kopen|koop|sell|verkopen|verkoop)\s+(?:some\s+)?([A-Za-z][A-Za-z0-9_]{1,19})\b",
        text,
        re.I,
    )
    if not m:
        return None
    symbol = m.group(1).upper()
    return None if symbol.lower() in {"for","me","it","this","token","usdc","some"} else symbol


def _recipient(text):
    matches = re.findall(r"(?<![\w@])@([A-Za-z0-9_]{2,32})\b", text)
    return matches[-1] if matches else None


def trade_action_slots(text):
    """Extract only the explicit, non-sensitive slots needed for a trade intent."""
    text = text if isinstance(text, str) else ""
    wants_sell = bool(SELL_WORD.search(text))
    wants_buy = bool(BUY_WORD.search(text))
    return {
        "action": "sell" if wants_sell and not wants_buy else ("buy" if wants_buy else None),
        "symbol": _token_symbol(text),
        "amount_sol": _amount_sol(text),
        "amount_usdc": _amount_usdc(text),
    }


def merge_trade_action_slots(base=None, update=None):
    """Merge conversation slots; the newest explicit value wins."""
    merged = {"action": None, "symbol": None, "amount_sol": None, "amount_usdc": None}
    for source in (base or {}, update or {}):
        for key in merged:
            value = source.get(key)
            if value is not None:
                merged[key] = value
        if source.get("amount_sol") is not None:
            merged["amount_usdc"] = None
        elif source.get("amount_usdc") is not None:
            merged["amount_sol"] = None
    return merged


def _trade_action_reply(text, context=None, action_state=None):
    current = trade_action_slots(text)
    slots = merge_trade_action_slots(action_state, current)
    amount_sol = slots["amount_sol"]
    amount_usdc = slots["amount_usdc"]
    symbol = slots["symbol"]
    action = current["action"] or slots["action"]
    if context == "trade_action" and not action:
        action = "buy"
    action = action or "buy"
    if action == "buy":
        if amount_usdc and not amount_sol:
            token_part = (" for $" + symbol) if symbol else ""
            return (
                "trade_action",
                "Buys use SOL, not USDC. Tell me how much SOL you want to use" + token_part + ". "
                "I’ll show the quote and costs first; you approve it in Phantom before anything is submitted.",
            )
        if symbol and amount_sol:
            if context == "trade_action" and action_state:
                if re.search(
                    r"\b(?:already told you|told you already|i told you|zei ik al|heb ik al gezegd|had ik al gezegd)\b",
                    text,
                    re.I,
                ):
                    return (
                        "trade_action",
                        "You did — I have it: " + amount_sol + " SOL for $" + symbol + ". "
                        "The next step is the quote and costs; you approve it in Phantom before anything is submitted.",
                    )
                return (
                    "trade_action",
                    "Got it — " + amount_sol + " SOL for $" + symbol + ". I have both trade details. "
                    "The next step is the quote and costs; you approve it in Phantom before anything is submitted.",
                )
            return (
                "trade_action",
                "Yes — I can help set up a " + amount_sol + " SOL buy for $" + symbol + ". "
                "I’ll show the quote and costs first; you approve it in Phantom before anything is submitted.",
            )
        if symbol:
            return (
                "trade_action",
                "Yes — I can help set up a buy for $" + symbol + ". How much SOL do you want to use? "
                "You approve the transaction in Phantom before anything is submitted.",
            )
        if amount_sol:
            return (
                "trade_action",
                "Yes — I can help set up a " + amount_sol + " SOL buy. Which token do you want? "
                "You approve the transaction in Phantom before anything is submitted.",
            )
        return (
            "trade_action",
            "Yes — I can help set up the buy. Which token do you want, and how much SOL? "
            "I’ll show the quote and costs first; you approve it in Phantom before anything is submitted.",
        )

    if symbol:
        return (
            "trade_action",
            "Yes — I can help set up a sell for $" + symbol + ". How much do you want to sell? "
            "I’ll show the quote first; you approve it in Phantom before anything is submitted.",
        )
    return (
        "trade_action",
        "Yes — I can help set up the sell. Which token do you want to sell, and how much? "
        "I’ll show the quote first; you approve it in Phantom before anything is submitted.",
    )


def _transfer_action_reply(text):
    amount = _amount_usdc(text)
    recipient = _recipient(text)
    is_tip = bool(TIP_WORD.search(text))
    noun = "tip" if is_tip else "transfer"
    if amount and recipient:
        return (
            "transfer_action",
            "I can help set up a " + amount + " USDC " + noun + " to @" + recipient + ". "
            "You review the recipient and amount, then approve it in Phantom before anything is sent.",
        )
    if recipient:
        return (
            "transfer_action",
            "I can help set up the " + noun + " to @" + recipient + ". How much USDC do you want to send? "
            "You approve it in Phantom before anything is sent.",
        )
    if amount:
        return (
            "transfer_action",
            "I can help set up a " + amount + " USDC " + noun + ". Who do you want to send it to? "
            "You approve it in Phantom before anything is sent.",
        )
    return (
        "transfer_action",
        "I can help set up the " + noun + ". Who should receive it, and how much USDC do you want to send? "
        "You approve it in Phantom before anything is sent.",
    )


def specific(clean, context=None, action_state=None):
    """Resolve the requested action before broad topic FAQ matching."""
    text = clean.lower().strip()
    def has(pattern):
        return bool(re.search(pattern, text, re.I))
    def response(topic, text):
        return topic, text

    # Credentials take priority; these questions must never be treated as wallet steps.
    if has(r'seed|recovery phrase|private key|secret key|herstelzin|priv[eé]sleutel'):
        return None

    # Delegated action intent must win over broad FAQ keywords. A user asking
    # "can you buy for me?" is asking whether OrcAgent can help perform an
    # action, not asking for a tutorial on where the Buy button lives.
    delegated = bool(ACTION_REQUEST.search(text) and not INSTRUCTION_REQUEST.search(text))
    if delegated:
        if BUY_WORD.search(text) or SELL_WORD.search(text):
            return _trade_action_reply(text, context, action_state)
        if TRANSFER_WORD.search(text) or TIP_WORD.search(text):
            return _transfer_action_reply(text)
    if context == 'trade_action' and (action_state or _amount_sol(text) or _amount_usdc(text) or _token_symbol(text)):
        return _trade_action_reply(text, context, action_state)
    if has(r'\b(?:fee|fees|cost|costs|kosten|kost)\b') and not has(r'\b(?:creator|referral|reward|rewards)\b'):
        return response('fees', 'Your trade review shows the platform fee, network costs and any token-account rent before confirmation. Check Fees & costs in the Buy/Sell screen: '+MARKET)
    if has(r'\b(?:stop.?loss|take.?profit|sl|tp)\b'):
        if has(r'not|fail|miss|didn|werkt niet|mislukt'):
            return response('trading', 'A hit starts a sell attempt; the position stays open until confirmed. Check its status in Live Trades. Which token and error do you see? Never share wallet secrets.')
        return response('trading', 'The bot checks fresh prices against your SL/TP settings and starts a sale when a limit is hit. Confirmation depends on the swap succeeding. Review your position in Live Trades.')
    if has(r'\b(?:sell|selling|verkopen)\b') and not has(r'\b(?:buy|buying|kopen)\b'):
        return response('trading', 'Open your token in Live Market, tap Sell, choose the amount and review the quote. Confirm to submit; check the result before trying again. '+MARKET)
    if has(r'\b(?:buy|buying|purchase|kopen)\b'):
        return response('trading', 'Open Live Market, select the token, tap Buy or Sell and enter an amount. Review the quote and costs, then confirm. '+MARKET)
    if has(r'\b(?:portfolio|holdings?|balance|saldo)\b') and has(r'missing|not showing|not all|wrong|empty|ontbre|niet|leeg'):
        return response('portfolio', 'Open Portfolio and check that the connected wallet is the one you expect. Which token is missing, and on which chain? '+PORTFOLIO)
    if has(r'\b(?:wallet|phantom)\b') and has(r'\b(?:disconnect|disconnecting|log out|logout|afmelden)\b'):
        return response('wallet', 'Open your wallet/account menu and choose Disconnect. This ends the connection; it does not sell your holdings.')
    if has(r'\b(?:wallet|phantom|connect|login)\b') and has(r'not working|doesn.t|error|failed|stuck|werkt niet|fout|mislukt'):
        return response('bug', 'Open the app in Phantom’s browser, tap Connect wallet and approve. If it still fails, tell me the exact error and device. Never share your recovery phrase.')
    if has(r'\b(?:call|calls|analysis|analyse)\b') and has(r'publish|create|post|write|maken|plaatsen'):
        return response('calls', 'Tap POST, choose a token call, add your analysis and publish. Include the reasoning behind your idea; the recorded entry is a reference. '+HOME)
    if has(r'\b(?:card|kaart)\b') and has(r'share|save|download|delen|opslaan'):
        return response('share', 'Open the call, tap Share call, then Save card to download the image or Share on X to post the link. Your personal link tracks invitations.')
    if has(r'\b(?:reply|comment|repl(?:y|ies)|reactie)\b') and has(r'\b(?:tag|mention|@)') :
        return response('community', 'Type @ followed by the username in your reply and select the person from the suggestions. Tag @orcagent to ask me about the app.')
    if has(r'\b(?:notification|notificatie)\b'):
        return response('community', 'Tap the reply notification to open its post and highlighted reply. If it opens the wrong place, tell me which notification and what screen you reach.')
    if has(r'\b(?:creators?|reward|rewards)\b') and has(r'views|likes|post|posting|paid|earn'):
        return response('creator', 'Posting or getting likes does not earn a payout. The separate call-based Creator Rewards page is no longer part of OrcAgent. Token-launch creator fees are managed from Token Launch: https://orcagent.fun/token-launch')
    if has(r'\b(?:referral|referrals)\b') and has(r'20|volume|fee|fees|percent'):
        return response('referral', 'The 20% referral share is a share of attributed trading fees, not 20% of the trade amount. View your link and earnings: https://orcagent.fun/referrals')
    if has(r'^\s*(?:how|where|what next|how do i do (?:that|it)|where do i find (?:that|it)|and then|hoe|waar)[\s?!.]*$') and context:
        guides = {
            'trading': 'Open Live Market, choose your token, select Buy or Sell, enter an amount and review the quote before confirming. '+MARKET,
            'wallet': 'Tap Connect wallet, select Phantom and approve the connection in Phantom. Return to OrcAgent; never enter your recovery phrase into a comment.',
            'portfolio': 'Tap Portfolio in the bottom navigation to view your connected wallet holdings. '+PORTFOLIO,
            'share': 'Open your call, tap Share call, then choose Copy link, Share on X or Save card.',
            'calls': 'Tap POST to publish a call, or open Calls in the home feed to read one. '+HOME,
            'referral': 'Open Referrals and copy your personal invitation link. https://orcagent.fun/referrals',
            'creator': 'The separate call-based Creator Rewards page is retired. Token-launch creator fees are managed from Token Launch: https://orcagent.fun/token-launch',
        }
        if context in guides:
            return response(context, guides[context])
    return None
