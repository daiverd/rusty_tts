"""ARPAbet phoneme -> Votrax SC-01A phoneme code mapping.

The Votrax SC-01A phoneme table (address -> name) below comes directly from
MAME's votrax.cpp source (`s_phone_table`, BSD-3-Clause) - it's the chip's
public register-level interface, distinct from the proprietary mask-ROM
formant/duration data itself.

The ARPAbet -> Votrax correspondence (including which stressed/unstressed
variant to use for AA/AE/AH/AO/EH/IH, and how to decompose diphthongs into
two-phone sequences) is adapted from the community-maintained mapping in
Echoshard/Votrax-Python-Synthesizer (MIT License, Chris Castaldi,
https://github.com/Echoshard/Votrax-Python-Synthesizer), which hand-tuned
these choices by ear against the real chip. Input phonemes are expected in
CMU Pronouncing Dictionary / ARPAbet form with stress digits, e.g. as
produced by g2p_en (see providers/votrax.py).
"""

from typing import List

# name -> Votrax phone address (0-63)
PHONE_ADDRESS = {
    "EH3": 0, "EH2": 1, "EH1": 2, "PA0": 3, "DT": 4, "A1": 5, "A2": 6, "ZH": 7,
    "AH2": 8, "I3": 9, "I2": 10, "I1": 11, "M": 12, "N": 13, "B": 14, "V": 15,
    "CH": 16, "SH": 17, "Z": 18, "AW1": 19, "NG": 20, "AH1": 21, "OO1": 22, "OO": 23,
    "L": 24, "K": 25, "J": 26, "H": 27, "G": 28, "F": 29, "D": 30, "S": 31,
    "A": 32, "AY": 33, "Y1": 34, "UH3": 35, "AH": 36, "P": 37, "O": 38, "I": 39,
    "U": 40, "Y": 41, "T": 42, "R": 43, "E": 44, "W": 45, "AE": 46, "AE1": 47,
    "AW2": 48, "UH2": 49, "UH1": 50, "UH": 51, "O2": 52, "O1": 53, "IU": 54, "U1": 55,
    "THV": 56, "TH": 57, "ER": 58, "EH": 59, "E1": 60, "AW": 61, "PA1": 62, "STOP": 63,
}

# Simple (single-phone) consonants: CMU symbol -> Votrax name
_CONSONANTS = {
    "B": "B", "CH": "CH", "D": "D", "DH": "THV", "F": "F", "G": "G",
    "HH": "H", "JH": "J", "K": "K", "L": "L", "M": "M", "N": "N",
    "NG": "NG", "P": "P", "R": "R", "S": "S", "SH": "SH", "T": "T",
    "TH": "TH", "V": "V", "W": "W", "Y": "Y", "Z": "Z", "ZH": "ZH",
}

# Diphthongs: CMU symbol -> two-phone Votrax sequence
_DIPHTHONGS = {
    "AY": ("AH1", "Y1"),
    "OW": ("O1", "U1"),
    "OY": ("O1", "I3"),
    "AW": ("AH1", "AW2"),
    "EY": ("A1", "Y"),
    "IY": ("E1", "Y"),
    "UW": ("IU", "U1"),
}

# Stress-sensitive single vowels: CMU symbol -> (stressed-variant, unstressed-variant)
# CMU stress digit '1' (primary stress) selects the first; anything else
# (0 = none, 2 = secondary) selects the second.
_STRESS_VOWELS = {
    "AA": ("AH1", "A2"),
    "AE": ("AE1", "AE"),
    "AH": ("AH1", "AH"),
    "AO": ("AW1", "AW"),
    "EH": ("EH2", "EH3"),
    "IH": ("I1", "I2"),
}

# Vowels with a single Votrax code regardless of stress
_PLAIN_VOWELS = {
    "ER": "ER",
    "UH": "OO1",
}


def _phone_for_token(token: str) -> List[int]:
    letters = "".join(c for c in token if c.isalpha())
    stress = token[-1] if token and token[-1].isdigit() else None

    if not letters:
        return []
    if letters in _CONSONANTS:
        return [PHONE_ADDRESS[_CONSONANTS[letters]]]
    if letters in _DIPHTHONGS:
        return [PHONE_ADDRESS[n] for n in _DIPHTHONGS[letters]]
    if letters in _STRESS_VOWELS:
        stressed, unstressed = _STRESS_VOWELS[letters]
        return [PHONE_ADDRESS[stressed if stress == "1" else unstressed]]
    if letters in _PLAIN_VOWELS:
        return [PHONE_ADDRESS[_PLAIN_VOWELS[letters]]]
    return []


# g2p_en emits a bare " " token between every word regardless of any actual
# punctuation - treating each of those as a pause (as an earlier version of
# this function did) put a full pause phone between literally every word,
# which reads as unnaturally gappy/robotic since Votrax's own phone-to-phone
# coarticulation already provides word separation. Real pauses belong at
# punctuation instead: comma-level marks get the shorter of the two ROM
# pause phones, sentence-enders get the longer one (measured from the
# actual sc01a.bin ROM's duration fields - PA1 is ~74ms, PA0 is ~244ms at
# the default 720kHz clock, despite what the naming might suggest).
_COMMA_PUNCTUATION = {",", ";", ":", "-", "--"}
_SENTENCE_PUNCTUATION = {".", "!", "?"}


def arpabet_to_phones(tokens: List[str], comma_pause: str = "PA1", sentence_pause: str = "PA0") -> List[int]:
    """Convert a list of ARPAbet tokens (as produced by g2p_en's G2p(), e.g.
    ['HH', 'AH0', 'L', 'OW1', ' ', 'W', 'ER1', 'L', 'D']) into a list of
    Votrax SC-01A phone addresses. Plain word-boundary spaces are dropped
    (words flow together); punctuation tokens contribute a pause phone
    instead - comma-level marks a short one, sentence-enders a long one -
    with consecutive punctuation/space tokens collapsing into a single
    pause rather than stacking."""
    codes: List[int] = []
    pending_pause = None
    for token in tokens:
        if token == " ":
            continue
        if token in _SENTENCE_PUNCTUATION:
            pending_pause = sentence_pause
            continue
        if token in _COMMA_PUNCTUATION:
            if pending_pause is None:
                pending_pause = comma_pause
            continue
        if pending_pause is not None:
            codes.append(PHONE_ADDRESS[pending_pause])
            pending_pause = None
        codes.extend(_phone_for_token(token))
    if pending_pause is not None:
        codes.append(PHONE_ADDRESS[pending_pause])
    return codes


def phones_to_bytes(codes: List[int]) -> bytes:
    return bytes(codes)
