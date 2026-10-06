"""Specific, reviewed English product answers. No model calls or invented account facts."""
import re

HOME = 'https://orcagent.fun/#app-home'
MARKET = 'https://orcagent.fun/live-market'
PORTFOLIO = 'https://orcagent.fun/#app-portfolio'

def specific(clean, context=None):
    """Resolve the requested action before broad topic FAQ matching."""
    text = clean.lower().strip()
    def has(pattern):
        return bool(re.search(pattern, text, re.I))
    def response(topic, text):
        return topic, text

    # Credentials take priority; these questions must never be treated as wallet steps.
    if has(r'seed|recovery phrase|private key|secret key|herstelzin|priv[eé]sleutel'):
        return None
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
