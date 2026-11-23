"""Order-preserving, prefix-free byte keys for sibling codes.

ordpath_key(code): tuple of signed integers, lexicographic order.
rational_key(q): exact rational, numeric order, via the continued fraction
[a0; a1, ..., an] (canonical, an >= 2 when n >= 1). Terms at odd positions are
complemented because a larger term there gives a smaller value; the end of the
expansion is encoded as an infinite term. Each term is length-prefixed.
"""
from fractions import Fraction

INF = b"\xff"


def _term(value):
    body = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    assert len(body) < 255
    return bytes([len(body)]) + body


def _invert(data):
    return bytes(255 - b for b in data)


def _positive(q):
    p, r = q.numerator, q.denominator
    terms = []
    while True:
        a, rem = divmod(p, r)
        terms.append(a)
        if rem == 0:
            break
        p, r = r, rem
    out = bytearray()
    for i, a in enumerate(terms + [None]):
        piece = INF if a is None else _term(a)
        out += _invert(piece) if i % 2 else piece
    return bytes(out)


def rational_key(q):
    q = Fraction(q)
    if q == 0:
        return b"\x02"
    if q > 0:
        return b"\x03" + _positive(q)
    return b"\x01" + _invert(_positive(-q))


def ordpath_key(code):
    out = bytearray()
    for v in code:
        assert -2**63 <= v < 2**63
        out += b"\x01" + (v + 2**63).to_bytes(8, "big")
    return bytes(out + b"\x00")


if __name__ == "__main__":
    import random
    rng = random.Random(7)
    values = {Fraction(rng.randint(-10**6, 10**6), rng.randint(1, 10**6)) for _ in range(20000)}
    values |= {Fraction(n, d) for n in range(-30, 31) for d in range(1, 31)}
    values |= {Fraction(2**200 + 1, 3**120), Fraction(-(5**90), 7)}
    ordered = sorted(values)
    assert sorted(values, key=rational_key) == ordered
    assert len({rational_key(v) for v in values}) == len(values)
    print("rational_key: order and uniqueness verified on", len(values), "values")
