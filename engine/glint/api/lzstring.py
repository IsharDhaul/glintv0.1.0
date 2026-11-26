"""`LZString.decompressFromEncodedURIComponent` (lz-string 1.5.0), for `?screen=` / `?s=`.

The web compresses Screen JSON with lz-string's URI-safe encoding (§2.12). This is a direct
port of the reference decompressor. lz-string works on UTF-16 code units, so the output is
assembled from code units and decoded at the end (astral characters arrive as surrogate pairs).
Tests check it against vectors produced by the JS library (`tests/api/lz_vectors.json`).
"""

KEY_STR_URI_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"
_BASE = {ch: i for i, ch in enumerate(KEY_STR_URI_SAFE)}
_RESET = 32


class LzStringError(ValueError):
    pass


class _Bits:
    def __init__(self, values: list[int]) -> None:
        self.values = values
        self.val = values[0] if values else 0
        self.position = _RESET
        self.index = 1

    def read(self, n: int) -> int:
        bits, power = 0, 1
        for _ in range(n):
            resb = self.val & self.position
            self.position >>= 1
            if self.position == 0:
                self.position = _RESET
                self.val = self.values[self.index] if self.index < len(self.values) else 0
                self.index += 1
            if resb:
                bits |= power
            power <<= 1
        return bits


def decompress_from_encoded_uri_component(encoded: str) -> str:
    """Raises LzStringError if `encoded` isn't valid lz-string URI-component output."""
    if encoded == "":
        raise LzStringError("empty input")
    text = encoded.replace(" ", "+")  # a `+` that went through form decoding
    try:
        values = [_BASE[ch] for ch in text]
    except KeyError as exc:
        raise LzStringError(f"invalid character {exc.args[0]!r}") from exc
    units = _decompress(values)
    return units.encode("utf-16-le", "surrogatepass").decode("utf-16-le")


def _decompress(values: list[int]) -> str:
    length = len(values)
    bits = _Bits(values)
    dictionary: dict[int, str] = {}
    enlarge_in, dict_size, num_bits = 4, 4, 3

    first = bits.read(2)
    if first == 2:
        return ""
    if first not in (0, 1):
        raise LzStringError("bad header")
    c = chr(bits.read(8 if first == 0 else 16))
    dictionary[3] = c
    w = c
    result = [c]
    while True:
        if bits.index > length:
            raise LzStringError("truncated input")
        code = bits.read(num_bits)
        if code in (0, 1):
            dictionary[dict_size] = chr(bits.read(8 if code == 0 else 16))
            code = dict_size
            dict_size += 1
            enlarge_in -= 1
        elif code == 2:
            return "".join(result)
        if enlarge_in == 0:
            enlarge_in = 2**num_bits
            num_bits += 1
        if code in dictionary:
            entry = dictionary[code]
        elif code == dict_size:
            entry = w + w[0]
        else:
            raise LzStringError("corrupt input")
        result.append(entry)
        dictionary[dict_size] = w + entry[0]
        dict_size += 1
        enlarge_in -= 1
        w = entry
        if enlarge_in == 0:
            enlarge_in = 2**num_bits
            num_bits += 1
