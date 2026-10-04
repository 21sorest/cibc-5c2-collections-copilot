"""Auditable baseline, not an LLM. Evidence is reviewed before any action."""
import re
import unicodedata

VERSION = 'rules-v0.4'
PATTERNS = {
    'hardship': r'job loss|lost (?:my |their |his |her )?job|laid off|layoff|position (?:was )?eliminated|(?:hours|shifts|pay).{0,35}(?:cut|reduced)|reduced (?:hours|income|pay)|pay cut|waiting for (?:ei|employment insurance)|hardship|struggling|budget (?:very )?tight|money is tight|things are hard this month|(?:can.t|cannot|unable to) afford|(?:can.t|cannot) pay (?:the whole|that amount)|not able to pay|don.t have the money|payment went up.{0,25}rate reset|perdu (?:mon |son )?emploi|heures.*(?:reduites|coupees)|moins d.heures|mise? a pied|pas de revenu|difficile financierement|c.est serre|un seul revenu|attend l.ae',
    'callback': r'\bcb scheduled\b|\bcall back\b|callback (?:requested|scheduled)|call (?:me|us|them) (?:back|later|after|tomorrow)|rappel|rappelez',
    'cease': r'stop (?:calling|contacting|texting)|do not (?:call|contact)|don.t (?:call|contact)|cease (?:contact|communication)|ne.*appelez',
    'insolvency': r'bankrupt|consumer proposal|insolvency|faillite|proposition de consommateur',
    'dispute': r'\bdisput|not (?:my|their) (?:charge|transaction)|payment (?:was )?not applied|conteste|litige|releve.*errone|don.t agree.{0,20}charge|statement.{0,15}wrong|amounts don.t add up|charges aren.t mine|why was i charged a late fee',
}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))


def negated_match(normalized,match):
    prefix=normalized[max(0,match.start()-45):match.start()]
    suffix=normalized[match.end():match.end()+30]
    return bool(re.search(r'\b(?:no|not|denies|without|haven.t|hasn.t|didn.t|isn.t|wasn.t)(?:\s+(?:financial|evidence|of|any|reported|current))*\s*$',prefix)
        or re.search(r'^\s+(?:(?:is|was|does)\s+)?(?:not applicable|not present|absent|denied)\b',suffix))


def has_negated_signal(text,signal):
    normalized=normalize(text)
    return any(negated_match(normalized,match) for match in re.finditer(PATTERNS[signal],normalized))


def extract(text):
    normalized = normalize(text)
    result = {}
    for signal, pattern in PATTERNS.items():
        # Scan all mentions so an early denial does not hide a later positive statement.
        result[signal] = any(not negated_match(normalized,match) for match in re.finditer(pattern,normalized))
    return result


def redact(text):
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', text)
    text = re.sub(r'(?<!\w)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\w)', '[phone]', text)
    text = re.sub(r'\b(?:\d[ -]?){13,19}\b', '[account number]', text)
    text = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '[date]', text)
    return text
