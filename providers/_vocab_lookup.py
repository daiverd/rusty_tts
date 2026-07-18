"""Shared word/phrase/index resolution for the vocabulary-lookup speech-chip
engines (providers/snspell.py, providers/s14001a_calculator.py). These
engines can only speak entries that exist verbatim in a fixed vocabulary
table baked into a real ROM - there is no open-text synthesis path - so
both need the same left-to-right tokenize-and-resolve logic: greedy
longest-phrase-first word matching, plus a `#N` syntax to refer to a
vocabulary entry by its 1-based position instead of by name (see
resolve_tokens's docstring).
"""
import re
from typing import Dict, List, Optional, Tuple, TypeVar

T = TypeVar("T")

_WORD_RE = re.compile(r"#\d+|[A-Za-z0-9']+")
_INDEX_RE = re.compile(r"^#(\d+)$")


def tokenize(text: str) -> List[str]:
    """Splits input into a left-to-right sequence of tokens, each either a
    plain uppercased word or a literal `#<digits>` index reference (case of
    the '#' form doesn't matter, digits are kept as-is)."""
    tokens = []
    for tok in _WORD_RE.findall(text):
        tokens.append(tok if tok.startswith("#") else tok.upper())
    return tokens


def resolve_tokens(tokens: List[str], vocab: Dict[Tuple[str, ...], T]) -> Optional[List[T]]:
    """Resolves a tokenize()'d sequence against a phrase-keyed vocabulary
    dict (tuple-of-words -> value, e.g. {("WRONG",): addr, ("SPELL", "IT"):
    addr}), in the same order the entries were inserted (Python dicts
    preserve insertion order since 3.7 - every engine using this must build
    its vocab dict in a fixed, deterministic order for `#N` to mean
    anything stable).

    Each token is either:
      - `#N`: resolves to the value of the Nth vocabulary entry (1-based,
        by insertion order). Out of range or non-numeric-looking (already
        filtered by tokenize's regex, but N=0 is still invalid since
        positions start at 1) fails the whole request.
      - a plain word: matched against `vocab` using greedy longest-phrase-
        first matching starting at that position, same as this project's
        existing word/phrase resolution.

    All-or-nothing: any unresolvable token (unmatched word, or malformed/
    out-of-range index) fails the entire request and returns None - no
    partial output, matching every other vocabulary-lookup engine's
    existing failure semantics.
    """
    if not tokens:
        return None

    values = list(vocab.values())
    max_phrase_len = max((len(k) for k in vocab), default=1)

    resolved: List[T] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("#"):
            m = _INDEX_RE.match(tok)
            if not m:
                return None
            n = int(m.group(1))
            if n < 1 or n > len(values):
                return None
            resolved.append(values[n - 1])
            i += 1
            continue

        matched = False
        for n in range(min(max_phrase_len, len(tokens) - i), 0, -1):
            span = tokens[i:i + n]
            if any(w.startswith("#") for w in span):
                continue
            value = vocab.get(tuple(span))
            if value is not None:
                resolved.append(value)
                i += n
                matched = True
                break
        if not matched:
            return None

    return resolved
