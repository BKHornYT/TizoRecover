"""Test samples for the 0.7.0 types (formats_extra.py), built to each format's own layout."""

from __future__ import annotations

import bz2
import lzma
import random
import struct
import zlib


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _payload(rng: random.Random, n: int) -> bytes:
    """Random bytes without MPEG start codes (0x00 never appears) and without long zero runs."""
    return bytes(rng.randrange(2, 256) for _ in range(n))


def make_mpg(vob: bool = False) -> tuple[bytes, str]:
    rng = _rng(31)
    out = bytearray()
    for k in range(25):
        scr = bytes([0x44, 0x00, 0x04, 0x00, 0x04, 0x01, 0x01, 0x89, 0xC3, 0xF8])     # MPEG-2 pack, no stuffing
        out += b"\x00\x00\x01\xba" + scr
        if k == 0:
            out += b"\x00\x00\x01\xbb" + struct.pack(">H", 12) + _payload(rng, 12)
        body = _payload(rng, 400)
        out += b"\x00\x00\x01\xe0" + struct.pack(">H", len(body)) + body
        if vob:
            audio = _payload(rng, 120)
            out += b"\x00\x00\x01\xbd" + struct.pack(">H", len(audio)) + audio
    out += b"\x00\x00\x01\xb9"
    return bytes(out), "vob" if vob else "mpg"


def make_m1v(mpeg2: bool = False) -> tuple[bytes, str]:
    rng = _rng(32)
    seq = b"\x00\x00\x01\xb3" + bytes([0x16, 0x01, 0x20, 0x13, 0xFF, 0xFF, 0xE0, 0x18])   # 352x288, 25 fps
    out = bytearray(seq)
    if mpeg2:
        out += b"\x00\x00\x01\xb5" + bytes([0x14, 0x8A, 0x00, 0x01, 0x00, 0x00])
    for g in range(3):
        out += b"\x00\x00\x01\xb8" + bytes([0x00, 0x08, 0x00, 0x40])
        for pic in range(5):
            out += b"\x00\x00\x01\x00" + bytes([pic << 6 & 0xFF, 0x0F, 0xFF, 0xF8])
            for sl in range(1, 4):
                out += bytes([0, 0, 1, sl]) + _payload(rng, 150)
    out += b"\x00\x00\x01\xb7"
    return bytes(out), "m2v" if mpeg2 else "m1v"


def make_dav() -> tuple[bytes, str]:
    rng = _rng(33)
    out = bytearray()
    for k in range(15):
        body = rng.randbytes(500 + k * 37)
        size = 24 + len(body) + 8
        head = b"DHAV" + bytes([0xFD, 0x00, 0x00, 0x00]) + struct.pack("<II", k, size) + rng.randbytes(8)
        out += head + body + b"dhav" + struct.pack("<I", size)
    return bytes(out), "dav"


def make_rm() -> tuple[bytes, str]:
    rng = _rng(34)
    def chunk(cid, body):
        return cid + struct.pack(">I", 8 + len(body)) + body
    out = chunk(b".RMF", b"\x00\x00" + struct.pack(">II", 0, 4))
    out += chunk(b"PROP", b"\x00\x00" + rng.randbytes(40))
    out += chunk(b"MDPR", b"\x00\x00" + b"RV40" + rng.randbytes(60))
    out += chunk(b"DATA", b"\x00\x00" + rng.randbytes(3000))
    out += chunk(b"INDX", b"\x00\x00" + rng.randbytes(40))
    return out, "rmvb"


def make_swf(compressed: bool = False) -> tuple[bytes, str]:
    body = _rng(35).randbytes(2000) + b"\x40\x00" * 10
    total = 8 + len(body)
    if compressed:
        return b"CWS\x0a" + struct.pack("<I", total) + zlib.compress(body, 6), "swf"
    return b"FWS\x0a" + struct.pack("<I", total) + body, "swf"


def make_mxf() -> tuple[bytes, str]:
    rng = _rng(36)
    key = b"\x06\x0e\x2b\x34"
    def klv(k12, body):
        n = len(body)
        ber = bytes([n]) if n < 0x80 else b"\x83" + n.to_bytes(3, "big")
        return key + k12 + ber + body
    out = klv(b"\x02\x05\x01\x01\x0d\x01\x02\x01\x01\x02\x04\x00", rng.randbytes(88))
    for k in range(12):
        out += klv(b"\x01\x02\x01\x01\x0d\x01\x03\x01\x15\x01\x05\x00", rng.randbytes(300 + k))
    out += klv(b"\x02\x05\x01\x01\x0d\x01\x02\x01\x01\x04\x04\x00", rng.randbytes(88))
    return out, "mxf"


def make_amr() -> tuple[bytes, str]:
    rng = _rng(37)
    out = bytearray(b"#!AMR\n")
    for _ in range(80):
        out += bytes([0x3C]) + rng.randbytes(31)       # mode 7 (12.2 kbit/s), 32-byte frames
    return bytes(out), "amr"


def make_ape() -> tuple[bytes, str]:
    rng = _rng(38)
    desc, header, seek, hdata, frames, term = 52, 24, 16, 0, 4000, 0
    d = b"MAC " + struct.pack("<HH", 3990, 0) + struct.pack("<7I", desc, header, seek, hdata, frames, 0, term) + rng.randbytes(16)
    return d + rng.randbytes(header + seek + hdata + frames + term), "ape"


def make_au() -> tuple[bytes, str]:
    data = _rng(39).randbytes(5000)
    return b".snd" + struct.pack(">5I", 24, len(data), 3, 44100, 2) + data, "au"


def make_caf() -> tuple[bytes, str]:
    rng = _rng(40)
    desc = struct.pack(">d", 44100.0) + b"lpcm" + struct.pack(">6I", 2, 4, 1, 2, 16, 0)[:20]
    out = b"caff\x00\x01\x00\x00" + b"desc" + struct.pack(">q", len(desc)) + desc
    data = b"\x00\x00\x00\x00" + rng.randbytes(4000)
    out += b"data" + struct.pack(">q", len(data)) + data
    return out, "caf"


def _boxes(sig_type: bytes, brand: bytes, body_type: bytes, body: bytes) -> bytes:
    sig = b"\x00\x00\x00\x0c" + sig_type + b"\r\n\x87\n"
    ftyp = struct.pack(">I", 20) + b"ftyp" + brand + b"\x00\x00\x00\x00" + brand
    return sig + ftyp + struct.pack(">I", 8 + len(body)) + body_type + body


def make_jp2() -> tuple[bytes, str]:
    rng = _rng(41)
    jp2h = struct.pack(">I", 8 + 22) + b"jp2h" + struct.pack(">I", 22) + b"ihdr" + rng.randbytes(14)
    code = b"\xff\x4f\xff\x51" + rng.randbytes(1500).replace(b"\xff\xd9", b"\xff\xd8") + b"\xff\xd9"
    sig = b"\x00\x00\x00\x0cjP  \r\n\x87\n"
    ftyp = struct.pack(">I", 20) + b"ftyp" + b"jp2 " + b"\x00\x00\x00\x00" + b"jp2 "
    return sig + ftyp + jp2h + struct.pack(">I", 8 + len(code)) + b"jp2c" + code, "jp2"


def make_jxl() -> tuple[bytes, str]:
    return _boxes(b"JXL ", b"jxl ", b"jxlc", b"\xff\x0a" + _rng(42).randbytes(1800)), "jxl"


def make_djvu() -> tuple[bytes, str]:
    rng = _rng(43)
    info = b"INFO" + struct.pack(">I", 10) + rng.randbytes(10)
    body = b"DJVU" + info + b"Sjbz" + struct.pack(">I", 900) + rng.randbytes(900)
    return b"AT&TFORM" + struct.pack(">I", len(body)) + body, "djvu"


def make_ps(eps: bool = False) -> tuple[bytes, str]:
    head = b"%!PS-Adobe-3.0 EPSF-3.0\n" if eps else b"%!PS-Adobe-3.0\n"
    body = b"%%BoundingBox: 0 0 100 100\n" + b"newpath 10 10 moveto 90 90 lineto stroke\n" * 60 + b"showpage\n"
    return head + body + b"%%EOF\n", "eps" if eps else "ps"


def make_eps_bin() -> tuple[bytes, str]:
    ps, _ = make_ps(True)
    tiff = b"II*\x00" + _rng(44).randbytes(800)
    head_len = 30
    header = b"\xc5\xd0\xd3\xc6" + struct.pack("<6I", head_len, len(ps), 0, 0, head_len + len(ps), len(tiff)) + b"\xff\xff"
    return header + ps + tiff, "eps"


def make_pst() -> tuple[bytes, str]:
    rng = _rng(45)
    total = 0x4400
    h = bytearray(rng.randbytes(0x200))
    h[0:4] = b"!BDN"
    h[8:10] = b"SM"
    h[10:12] = struct.pack("<H", 23)
    h[0xB8:0xC0] = struct.pack("<Q", total)
    return bytes(h) + rng.randbytes(total - 0x200), "pst"


def make_bz2() -> tuple[bytes, str]:
    text = b"".join(b"line %d of a recovered log file\n" % i for i in range(800))
    return bz2.compress(text), "bz2"


def make_xz() -> tuple[bytes, str]:
    text = b"".join(b"row %d;value %d\n" % (i, i * i) for i in range(900))
    return lzma.compress(text, format=lzma.FORMAT_XZ), "xz"


def make_cab() -> tuple[bytes, str]:
    rng = _rng(46)
    total = 2000
    head = b"MSCF" + b"\x00" * 4 + struct.pack("<I", total) + b"\x00" * 4 + struct.pack("<I", 44) + b"\x00" * 4 + bytes([3, 1]) \
        + struct.pack("<HHHH", 1, 1, 0, 0)
    return head + rng.randbytes(total - len(head)), "cab"


def make_dex() -> tuple[bytes, str]:
    rng = _rng(47)
    total = 3000
    h = bytearray(b"dex\n035\x00" + rng.randbytes(0x18))
    h += struct.pack("<III", total, 0x70, 0x12345678)
    return bytes(h) + rng.randbytes(total - len(h)), "dex"


EXTRA_BUILDERS = {
    "mpg": make_mpg, "vob": lambda: make_mpg(True), "m1v": make_m1v, "m2v": lambda: make_m1v(True),
    "dav": make_dav, "rmvb": make_rm, "swf": make_swf, "swfz": lambda: make_swf(True), "mxf": make_mxf,
    "amr": make_amr, "ape": make_ape, "au": make_au, "caf": make_caf, "jp2": make_jp2, "jxl": make_jxl,
    "djvu": make_djvu, "ps": make_ps, "eps": lambda: make_ps(True), "epsb": make_eps_bin, "pst": make_pst,
    "bz2": make_bz2, "xz": make_xz, "cab": make_cab, "dex": make_dex,
}
