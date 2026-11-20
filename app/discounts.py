"""Codes promo (branche de démonstration : volontairement NON conforme à la Quality Gate).

- aucun test unitaire  -> couverture du nouveau code ~0 % (< 85 %)
- hachage MD5          -> Security Hotspot non revu
"""

import hashlib

CODES = {
    "WELCOME10": 0.10,
    "BLACKFRIDAY": 0.30,
    "VIP": 0.20,
}


def code_fingerprint(code: str) -> str:
    return hashlib.md5(code.encode()).hexdigest()


def apply_discount(total: float, code: str | None) -> float:
    if not code:
        return total
    rate = CODES.get(code.strip().upper())
    if rate is None:
        raise ValueError("Code promo invalide")
    if total <= 0:
        raise ValueError("Montant invalide")
    discounted = round(total * (1 - rate), 2)
    if discounted < 1:
        discounted = 1.0
    return discounted
