"""Turn numbers into radio speech."""
from __future__ import annotations

_D = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
      "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "niner"}
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def digits(n: int | str, width: int | None = None) -> str:
    s = str(int(n)) if not isinstance(n, str) else n
    if width:
        s = s.zfill(width)
    return " ".join(_D[c] for c in s if c in _D)


def heading3(deg: float) -> str:
    h = int(round(deg)) % 360 or 360        # radio convention: north is 360, not 000
    return digits(h, 3)


def _below_100(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))


def thousands(feet: float) -> str:
    """22,400 ft -> 'twenty-two thousand'; under 1000 -> 'below one thousand'."""
    k = int(round(feet / 1000))
    if k <= 0:
        return "below one thousand"
    return f"{_below_100(k)} thousand" if k < 100 else f"{digits(k)} thousand"


def miles(nm: float) -> str:
    n = int(round(nm))
    return digits(n) if n < 10 else _below_100(n) if n < 100 else digits(n)


def callsign_speech(cs: str) -> str:
    """'Viper 1-1' -> 'Viper one one'."""
    out = []
    for tok in cs.replace("-", " ").split():
        out.append(digits(tok) if tok.isdigit() else tok)
    return " ".join(out)
