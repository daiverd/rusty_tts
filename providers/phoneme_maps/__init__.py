"""Shared g2p_en accessor for allophone-chip providers (sp0256, votrax).

g2p_en's G2p object loads CMUdict + a small OOV model at construction time
(a few hundred ms); build it once per process and reuse across requests.
"""

_g2p = None


def get_g2p():
    global _g2p
    if _g2p is None:
        from g2p_en import G2p
        _g2p = G2p()
    return _g2p
