"""Provenance verification: is the model's quote really on the page?

Every value the model proposes carries {page, quote}. We search the quote in the
page text after a light, reversible normalisation (whitespace, hyphenation,
typographic quotes, case) and return the character span in the ORIGINAL page
text. A value whose quote cannot be found is rejected (removed), never kept.
"""
from __future__ import annotations

import re
import unicodedata

_TRANS = str.maketrans({
    "’": "'", "‘": "'", "‛": "'", "´": "'", "`": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "‑": "-", " ": " ", " ": " ",
})


def normalise(text: str) -> tuple[str, list[int]]:
    """Return (normalised text, index map normalised->original)."""
    out, idx = [], []
    prev_space = True
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        # drop soft hyphen and end-of-line hyphenation ("Verkehrs-\nwege")
        if c == "­":
            i += 1
            continue
        if c == "-" and i + 1 < n and text[i + 1] == "\n" and out and out[-1].isalpha():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j].islower():
                i = j
                continue
        c = unicodedata.normalize("NFC", c).translate(_TRANS).lower()[:1]  # "İ".lower() is 2 chars
        # punctuation/symbols compare as spaces: robust to « » spacing, quote styles, dashes
        if unicodedata.category(c)[0] in "PS":
            c = " "
        if c.isspace():
            if prev_space:
                i += 1
                continue
            c = " "
            prev_space = True
        else:
            prev_space = False
        out.append(c)
        idx.append(i)
        i += 1
    return "".join(out), idx


def norm_only(text: str) -> str:
    return normalise(text)[0].strip()


class PageIndex:
    def __init__(self, pages: list[str]):
        self.pages = pages
        self.norm = [normalise(p) for p in pages]
        # space-free view: some PDFs have no space glyphs ("RéponsedelaMunicipalité")
        self.tight = []
        for t, m in self.norm:
            keep = [i for i, c in enumerate(t) if c != " "]
            self.tight.append(("".join(t[i] for i in keep), [m[i] for i in keep]))
        self.used_tight = 0

    def find(self, quote: str, page: int | None) -> tuple[int, int, int] | None:
        """Return (page_number_1_based, start, end) in original text, or None."""
        q = norm_only(quote or "")
        if len(q) < 3:
            return None
        order = list(range(len(self.pages)))
        if isinstance(page, int) and 1 <= page <= len(self.pages):
            order.remove(page - 1)
            order.insert(0, page - 1)
        for pi in order:
            ntext, imap = self.norm[pi]
            k = ntext.find(q)
            if k < 0 and len(q) > 40:
                # long quotes: accept if both ends are found close together (model trimmed the middle)
                head, tail = q[:25], q[-25:]
                h = ntext.find(head)
                if h >= 0:
                    t = ntext.find(tail, h)
                    if t >= 0 and t - h < len(q) * 2:
                        return pi + 1, imap[h], imap[t + len(tail) - 1] + 1
                continue
            if k >= 0:
                return pi + 1, imap[k], imap[k + len(q) - 1] + 1
        qt = q.replace(" ", "")
        if len(qt) >= 8:
            for pi in order:
                ttext, tmap = self.tight[pi]
                k = ttext.find(qt)
                if k >= 0:
                    self.used_tight += 1
                    return pi + 1, tmap[k], tmap[k + len(qt) - 1] + 1
        return None

    def contains(self, value: str) -> bool:
        v = norm_only(value)
        if not v:
            return False
        vt = v.replace(" ", "")
        return any(v in n for n, _ in self.norm) or (len(vt) >= 8 and any(vt in t for t, _ in self.tight))


_DATE_PARTS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MONTHS = {
    1: ["jan", "janv", "genn", "jän"], 2: ["feb", "févr", "fevr", "febbr"], 3: ["mär", "märz", "mars", "marz", "marzo"],
    4: ["apr", "avr"], 5: ["mai", "mag"], 6: ["jun", "juin", "giu"], 7: ["jul", "juil", "lug"],
    8: ["aug", "août", "aout", "ago"], 9: ["sep", "sept", "set"], 10: ["okt", "oct", "ott"],
    11: ["nov"], 12: ["dez", "déc", "dec", "dic"],
}


def date_supported(value: str, quote: str) -> bool:
    """True if an ISO date's day, month and year all appear in the quote."""
    m = _DATE_PARTS.match(value or "")
    if not m:
        return False
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    q = norm_only(quote)
    if str(y) not in q and f"{y % 100:02d}" not in re.findall(r"\d+", q):
        return False
    nums = [int(x) for x in re.findall(r"\d+", q)]
    if d not in nums:
        return False
    if mo in nums:
        return True
    return any(name in q for name in MONTHS[mo])
