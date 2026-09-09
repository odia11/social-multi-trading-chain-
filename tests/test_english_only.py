"""The app is in English. All of it.

Dutch had collected in the interface a phrase at a time -- a settings
description here, a toast there, an admin button -- because whoever wrote a
line wrote it in the language they were thinking in. The result was a screen
that switched language halfway down.

TWO PLACES IT HID
Not just labels. The AI prompts were written in Dutch, and the model answers
in the language it is asked in -- so the reasoning shown beside a trade came
back Dutch no matter how many labels were translated. Translating the visible
strings alone would have left Dutch leaking in through the model, from a file
nobody would think to check.

And single common words. A filter looking for Dutch sentences sails straight
past "Vandaag", "Gisteren", "Bezig…" -- which are exactly the short labels a
UI is made of.

WHAT THIS GUARDS
Text that can reach a screen, plus the prompts, in the app's own files.
Comments are not checked: they are for whoever is reading the code, and this
session's own commit messages and comments are written in English anyway.
Vendored libraries are not ours to rewrite.
"""
import os
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SKIP_DIRS = ('.git/', 'node_modules/', 'tests/', 'venv/', 'deploy/', 'static/vendor/')
EXTS = ('.html', '.js', '.py')

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

# Words that are Dutch and are NOT also English words, so a hit is a hit.
# Split in two: phrases (need two to fire, keeping false positives down) and
# standalone UI words (one is enough, because that is all a button holds).
SENTENCE_WORDS = """niet|wordt|worden|jouw|deze|voor|van|naar|maar|nog|geen|wel|moet|moeten|
kun|kunt|kunnen|hebt|heeft|bent|opnieuw|elke|alleen|verbinden|verbonden|ontkoppel|
instellingen|opgeslagen|mislukt|gelukt|kosten|saldo|inzet|hoger|lager|beetje|
gefinancierd|netwerkkosten|handelssaldo|pagina|scherm|succesvol|proberen|probeer|
laden|straks|eerst|daarna|weinig|zoeken|zoekt|verzenden|versturen|bedrag|aantal|
toevoegen|verwijderen|bewerken|sluiten|openen|kiezen|gekozen|onderteken|verzoek|
inloggen|uitloggen|wissel|juiste|storting|aangevuld|voordat|zelf|handelen|
gebruikers|voorstellen|draait|dagelijks|schaalt|reden|gehouden|piek|winst|verlies"""
# Every word here must be Dutch and NOT English, since one hit is enough to
# fail. "analyse" was in this list and is also the British spelling, so it
# flagged a correctly-English prompt -- a test that cries wolf gets ignored,
# which is worse than not having it.
LABEL_WORDS = """vandaag|gisteren|morgen|opslaan|annuleren|bevestigen|bezig|
goedkeuren|afwijzen|instellen|wijzigen|kopieren|gekopieerd|onbekend|
overzicht|opbrengst|opname|geanalyseerd|voorstellen|actieve|
bekijken|verbergen|tonen|kijken|wijzigen|aanpassen|weergeven|
uitklappen|inklappen|vernieuwen|vervangen|herstellen|bewaren"""

SENT = re.compile(r'\b(' + SENTENCE_WORDS.replace('\n', '').replace(' ', '') + r')\b', re.I)
LABEL = re.compile(r'\b(' + LABEL_WORDS.replace('\n', '').replace(' ', '') + r')\b', re.I)

# A hand-written word list only ever catches the words someone thought of.
# "Per chain bekijken" shipped past the first version of this test for exactly
# that reason. So there is a second signal that does not depend on anyone's
# imagination: spelling patterns that are ordinary in Dutch and almost absent
# from English. "ij" (bekijken, wijzigen, prijs, tijd), and the doubled "aa"
# and "uu" (maar, jaar, naam, uur, duur) -- English has a handful of loanwords
# with these and no more.
SPELLING = re.compile(r'\b\w*(ij|aa|uu)\w*\b', re.I)
# The English words that do contain them, so a real one is not flagged.
SPELLING_OK = {'bazaar', 'bazaars', 'aardvark', 'salaam', 'kraal', 'markaz',
               'vacuum', 'vacuums', 'continuum', 'residuum', 'aaa', 'naan',
               'baa', 'raajd', 'fijian', 'beijing', 'hijack', 'hijacked',
               'hijacking', 'hijra', 'raiju', 'tijuana'}


def _spelling_hit(frag):
    """Does this look like Dutch spelling, in something that is prose?

    The signal is only meaningful in words. A wallet address, a base58
    alphabet, a hex hash and a uuid are all long runs of arbitrary characters
    and will contain 'aa' or 'ij' by chance -- flagging those would make the
    test noisy enough to be ignored, which is the one way it can fail
    completely.
    """
    if ' ' not in frag:
        return False                       # an identifier, not a sentence
    if re.search(r'[A-Za-z0-9]{20,}', frag):
        return False                       # an address, hash or alphabet
    for w in re.findall(r'[A-Za-z]+', frag):
        if len(w) > 15 or w.lower() in SPELLING_OK:
            continue
        if re.search(r'(ij|aa|uu)', w, re.I):
            return True
    return False


def shippable_strings(text):
    """Quoted strings and text between tags -- the things that can be seen.

    Comments are skipped. They explain the code to whoever maintains it and
    never reach a screen, so policing their language would only make this test
    noisy without making the app any more English.
    """
    out = []
    for lineno, line in enumerate(text.split('\n'), 1):
        stripped = line.strip()
        if stripped.startswith(('#', '//', '*', '/*')):
            continue
        for m in re.finditer(r"'([^'\n]{3,})'|\"([^\"\n]{3,})\"|>([^<>{}\n]{3,})<", line):
            frag = (m.group(1) or m.group(2) or m.group(3) or '').strip()
            if frag:
                out.append((lineno, frag))
    return out


def scan():
    hits = []
    for dirpath, _dirnames, filenames in os.walk(REPO):
        rel_dir = dirpath[len(REPO) + 1:] + '/'
        if any(rel_dir.startswith(s) for s in SKIP_DIRS):
            continue
        for name in sorted(filenames):
            if not name.endswith(EXTS):
                continue
            path = os.path.join(dirpath, name)
            try:
                text = open(path, encoding='utf-8').read()
            except Exception:
                continue
            for lineno, frag in shippable_strings(text):
                dutch = (len(SENT.findall(frag)) >= 2
                         or bool(LABEL.search(frag))
                         or _spelling_hit(frag))
                if dutch:
                    hits.append((path[len(REPO) + 1:], lineno, frag[:110]))
    return hits


found = scan()
for path, lineno, frag in found[:25]:
    print(f'   {path}:{lineno}: {frag}')
check('no Dutch left in anything that can reach a screen — labels, buttons, '
      'messages, placeholders and errors alike', not found)

# ── the one that would have been missed ───────────────────────────────────
# The model answers in the language it is asked in, so a Dutch prompt puts
# Dutch on the screen from a file that holds no labels at all.
APP = open(REPO + '/dashboard.py', encoding='utf-8').read()
prompts = re.findall(r"(?:system_prompt|user_prompt|prompt)\s*=\s*\((.*?)\n    \)", APP, re.S)
check('the AI prompts are in English too. The model replies in the language '
      'it is asked in, so a Dutch prompt would keep putting Dutch on the '
      'screen no matter how many labels were translated',
      prompts and not any(len(SENT.findall(p)) >= 2 or LABEL.search(p) for p in prompts))

check('...and there are prompts to check, so this is not passing on an empty '
      'search', len(prompts) >= 2)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
