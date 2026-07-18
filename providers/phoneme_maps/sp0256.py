"""ARPAbet phoneme -> SP0256-AL2 allophone code mapping.

The SP0256-AL2 allophone table (address -> name) below is well-documented,
widely-reproduced public data describing how to *drive* the chip (which
allophone address plays which sound) - distinct from the proprietary mask-ROM
waveform data itself. Cross-checked against multiple independent hobbyist/
retrocomputing sources (e.g. cerkit/sp0256-synth, ExtremeElectronics'
SP0256-AL2-Pico-Emulation-Detail).

The ARPAbet -> SP0256 correspondence itself (which of several similarly-named
allophones to use, e.g. ER1 vs ER2, UW1 vs UW2, HH1 vs HH2) is adapted from
greg-kennedy/p5-NRL-TextToPhoneme's `rules/ipa_to_sp0256.json` (Unlicense /
public domain, https://github.com/greg-kennedy/p5-NRL-TextToPhoneme) - despite
that project's filename, the ruleset is keyed by ARPAbet-style symbols that
match g2p_en's output almost exactly, so it's used directly here rather than
routed through IPA. It reflects that author's own tuning against real chip
output via their "SP0256-AL2 TTS Online" tool, not 1980s-original data.

Input phonemes are expected in CMU Pronouncing Dictionary / ARPAbet form with
stress digits, e.g. as produced by g2p_en (see providers/sp0256.py).
"""

from typing import List

# name -> SP0256-AL2 address (0-63)
ALLOPHONE_ADDRESS = {
    "PA1": 0, "PA2": 1, "PA3": 2, "PA4": 3, "PA5": 4,
    "OY": 5, "AY": 6, "EH": 7, "KK3": 8, "PP": 9,
    "JH": 10, "NN1": 11, "IH": 12, "TT2": 13, "RR1": 14,
    "AX": 15, "MM": 16, "TT1": 17, "DH1": 18, "IY": 19,
    "EY": 20, "DD1": 21, "UW1": 22, "AO": 23, "AA": 24,
    "YY2": 25, "AE": 26, "HH1": 27, "BB1": 28, "TH": 29,
    "UH": 30, "UW2": 31, "AW": 32, "DD2": 33, "GG3": 34,
    "VV": 35, "GG1": 36, "SH": 37, "ZH": 38, "RR2": 39,
    "FF": 40, "KK2": 41, "KK1": 42, "ZZ": 43, "NG": 44,
    "LL": 45, "WW": 46, "XR": 47, "WH": 48, "YY1": 49,
    "CH": 50, "ER1": 51, "ER2": 52, "OW": 53, "DH2": 54,
    "SS": 55, "NN2": 56, "HH2": 57, "OR": 58, "AR": 59,
    "YR": 60, "GG2": 61, "EL": 62, "BB2": 63,
}

# CMU/ARPAbet symbol (stress digit stripped) -> SP0256-AL2 allophone name.
# Ported from ipa_to_sp0256.json's rules (each "[X]=[Y]" rule -> X: "Y").
_ARPABET_TO_ALLOPHONE = {
    "IY": "IY", "IH": "IH", "EY": "EY", "EH": "EH", "AE": "AE",
    "AA": "AA", "AO": "AO", "OW": "OW", "UH": "UH", "UW": "UW1",
    "ER": "ER1", "AH": "UH", "AY": "AY", "AW": "AW", "OY": "OY",
    "Y": "YY1", "P": "PP", "B": "BB1", "T": "TT1", "D": "DD1",
    "K": "KK1", "G": "GG1", "F": "FF", "V": "VV", "TH": "TH",
    "DH": "DH1", "S": "SS", "Z": "ZZ", "SH": "SH", "ZH": "ZH",
    "HH": "HH1", "CH": "CH", "JH": "JH", "M": "MM", "N": "NN1",
    "NG": "NG", "L": "LL", "W": "WW", "R": "RR1",
}

# g2p_en emits these as standalone punctuation tokens; map per the PUNCT
# rules in ipa_to_sp0256.json.
_PUNCT_TO_ALLOPHONE = {
    ",": "PA4", "-": "PA4",
    ".": "PA5", "?": "PA5", "!": "PA5",
}


def _phone_for_token(token: str) -> List[int]:
    if token in _PUNCT_TO_ALLOPHONE:
        return [ALLOPHONE_ADDRESS[_PUNCT_TO_ALLOPHONE[token]]]

    letters = "".join(c for c in token if c.isalpha())
    if not letters or letters not in _ARPABET_TO_ALLOPHONE:
        return []
    return [ALLOPHONE_ADDRESS[_ARPABET_TO_ALLOPHONE[letters]]]


def arpabet_to_allophones(tokens: List[str], word_pause: str = "PA3") -> List[int]:
    """Convert a list of ARPAbet tokens (as produced by g2p_en's G2p(), e.g.
    ['HH', 'AH0', 'L', 'OW1', ' ', 'W', 'ER1', 'L', 'D']) into a list of
    SP0256-AL2 allophone addresses. Space tokens become `word_pause`;
    punctuation tokens map to their own pause lengths; anything else
    unrecognized is skipped."""
    codes: List[int] = []
    for token in tokens:
        if token == " ":
            codes.append(ALLOPHONE_ADDRESS[word_pause])
            continue
        codes.extend(_phone_for_token(token))
    return codes


def allophones_to_bytes(codes: List[int]) -> bytes:
    return bytes(codes)
