"""Small but structurally real samples of the D5 formats, for carving tests.

Each builder returns ``(bytes, ext)``: the file, and the type the carver should
name it (a NEF is a TIFF to its magic; only its contents say NEF).
"""

from __future__ import annotations

import random
import struct


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def make_tiff(kind: str = "tif") -> tuple[bytes, str]:
    """A little-endian TIFF with one strip; ``kind`` picks the RAW flavour."""
    pixels = _rng(1).randbytes(4096)
    make = {"nef": b"NIKON CORPORATION\x00", "arw": b"SONY\x00", "pef": b"PENTAX\x00"}.get(kind, b"")
    magic = {"orf": b"IIRO", "rw2": b"IIU\x00"}.get(kind, b"II*\x00")
    first_ifd = 16 if kind == "cr2" else 8
    head = bytearray(magic + struct.pack("<I", first_ifd))
    if kind == "cr2":
        head += b"CR\x02\x00" + struct.pack("<I", 0)
    entries = [(0x0100, 3, 1, 64), (0x0101, 3, 1, 64), (0x0102, 3, 1, 8)]
    if kind == "dng":
        entries.append((0xC612, 1, 4, 0x00000401))
    n = len(entries) + 2 + (1 if make else 0)
    table_end = first_ifd + 2 + n * 12 + 4
    make_at = table_end
    strip_at = make_at + len(make)
    if make:
        entries.append((0x010F, 2, len(make), make_at))
    entries += [(0x0111, 4, 1, strip_at), (0x0117, 4, 1, len(pixels))]
    entries.sort()
    ifd = struct.pack("<H", n) + b"".join(struct.pack("<HHII", *e) for e in entries) + struct.pack("<I", 0)
    data = bytes(head) + ifd + make + pixels
    return data, kind


def make_raf() -> tuple[bytes, str]:
    jpeg = b"\xff\xd8\xff\xdb" + _rng(2).randbytes(600) + b"\xff\xd9"
    cfa_hdr = _rng(3).randbytes(64)
    cfa = _rng(4).randbytes(3000)
    head = bytearray(b"FUJIFILMCCD-RAW 0201FF383501" + bytes(256))
    jpeg_at, hdr_at = 0x100, 0x100 + len(jpeg)
    cfa_at = hdr_at + len(cfa_hdr)
    struct.pack_into(">IIIIII", head, 84, jpeg_at, len(jpeg), hdr_at, len(cfa_hdr), cfa_at, len(cfa))
    data = bytes(head[:0x100]) + jpeg + cfa_hdr + cfa
    return data, "raf"


def _vint8(n: int) -> bytes:
    return b"\x01" + n.to_bytes(7, "big")


def make_mkv(webm: bool = False) -> tuple[bytes, str]:
    doctype = b"webm" if webm else b"matroska"
    body = b"\x42\x82" + bytes([0x80 | len(doctype)]) + doctype
    ebml = b"\x1a\x45\xdf\xa3" + bytes([0x80 | len(body)]) + body
    payload = b"\xec" + _vint8(5000) + _rng(5).randbytes(5000)       # a Void element
    segment = b"\x18\x53\x80\x67" + _vint8(len(payload)) + payload
    return ebml + segment, "webm" if webm else "mkv"


_ASF_HEADER = bytes.fromhex("3026B2758E66CF11A6D900AA0062CE6C")
_ASF_FILE_PROPS = bytes.fromhex("A1DCAB8C47A9CF118EE400C00C205365")
_ASF_STREAM = bytes.fromhex("9107DCB7B7A9CF118EE600C00C205365")
_ASF_VIDEO = bytes.fromhex("C0EF19BC4D5BCF11A8FD00805F5C442B")
_ASF_DATA = bytes.fromhex("3626B2758E66CF11A6D900AA0062CE6C")


def make_asf(video: bool = True) -> tuple[bytes, str]:
    data_body = _rng(6).randbytes(6000)
    stream = _ASF_STREAM + struct.pack("<Q", 16 + 8 + 16 + 16) + (_ASF_VIDEO if video else bytes(16)) + bytes(16)
    props_len = 104
    header_len = 30 + props_len + len(stream)
    data_obj = _ASF_DATA + struct.pack("<Q", 24 + len(data_body)) + data_body
    total = header_len + len(data_obj)
    props = bytearray(_ASF_FILE_PROPS + struct.pack("<Q", props_len) + bytes(16) + struct.pack("<Q", total))
    props += bytes(props_len - len(props))
    header = _ASF_HEADER + struct.pack("<QI", header_len, 2) + b"\x01\x02" + bytes(props) + stream
    return header + data_obj, "wmv" if video else "wma"


def make_flv() -> tuple[bytes, str]:
    out = bytearray(b"FLV\x01\x05\x00\x00\x00\x09" + bytes(4))
    for k, typ in enumerate((18, 9, 8, 9)):
        body = _rng(10 + k).randbytes(300 + k * 50)
        out += bytes([typ]) + len(body).to_bytes(3, "big") + bytes(4) + bytes(3) + body
        out += struct.pack(">I", 11 + len(body))
    return bytes(out), "flv"


def make_ts(m2ts: bool = False) -> tuple[bytes, str]:
    rng = _rng(7)
    out = bytearray()
    for k in range(60):
        head = b"\x47\x40\x00\x10" if k == 0 else bytes([0x47, 0x01, 0x00, 0x10 | (k & 0x0F)])
        packet = head + rng.randbytes(184).replace(b"\x47", b"\x46")
        out += (b"\x00\x00\x00\x00" + packet) if m2ts else packet
    return bytes(out), "m2ts" if m2ts else "ts"


def make_psd() -> tuple[bytes, str]:
    channels, height, width = 3, 6, 5
    head = b"8BPS" + struct.pack(">H6xHIIHH", 1, channels, height, width, 8, 3)
    sections = struct.pack(">I", 0) + struct.pack(">I", 12) + _rng(8).randbytes(12) + struct.pack(">I", 0)
    pixels = struct.pack(">H", 0) + _rng(9).randbytes(channels * height * width)
    return head + sections + pixels, "psd"


def make_aiff() -> tuple[bytes, str]:
    comm = b"COMM" + struct.pack(">IhIh", 18, 1, 2000, 16) + b"\x40\x0e\xac\x44" + bytes(6)
    ssnd_data = struct.pack(">II", 0, 0) + _rng(11).randbytes(4000)
    ssnd = b"SSND" + struct.pack(">I", len(ssnd_data)) + ssnd_data
    body = b"AIFF" + comm + ssnd
    return b"FORM" + struct.pack(">I", len(body)) + body, "aiff"


def make_midi() -> tuple[bytes, str]:
    events = b"\x00\x90\x3c\x40\x60\x80\x3c\x40\x00\xff\x2f\x00"
    track = b"MTrk" + struct.pack(">I", len(events)) + events
    return b"MThd" + struct.pack(">IHHH", 6, 1, 2, 96) + track + track, "mid"


def make_iso() -> tuple[bytes, str]:
    blocks = 24
    image = bytearray(blocks * 2048)
    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[40:48] = b"TIZOTEST"
    struct.pack_into("<I", pvd, 0x50, blocks)
    struct.pack_into(">I", pvd, 0x54, blocks)
    struct.pack_into("<H", pvd, 0x80, 2048)
    struct.pack_into(">H", pvd, 0x82, 2048)
    image[0x8000:0x8800] = pvd
    image[0x8800] = 0xFF
    image[0x8801:0x8806] = b"CD001"
    image[0x8806] = 1
    image[0x9000:0x9000 + 5000] = _rng(12).randbytes(5000)
    return bytes(image), "iso"


def make_ttf(otf: bool = False) -> tuple[bytes, str]:
    tags = [b"OS/2", b"cmap", b"head", b"hhea"]
    bodies = [_rng(20 + k).randbytes(40 + k * 12) for k in range(len(tags))]
    n = len(tags)
    out = bytearray((b"OTTO" if otf else b"\x00\x01\x00\x00") + struct.pack(">HHHH", n, 64, 2, 0))
    at = 12 + n * 16
    directory = bytearray()
    blobs = bytearray()
    for tag, body in zip(tags, bodies):
        padded = body + bytes((-len(body)) % 4)
        directory += tag + struct.pack(">III", 0, at + len(blobs), len(body))
        blobs += padded
    return bytes(out + directory + blobs), "otf" if otf else "ttf"


def make_rtf() -> tuple[bytes, str]:
    text = rb"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times;}}\f0 Recovered {\b bold} text, and more.\par }"
    return text + b"\r\n", "rtf"


def make_heic() -> tuple[bytes, str]:
    ftyp = struct.pack(">I", 24) + b"ftyp" + b"heic" + bytes(4) + b"mif1heic"
    meta = struct.pack(">I", 40) + b"meta" + _rng(30).randbytes(32)
    mdat = struct.pack(">I", 2008) + b"mdat" + _rng(31).randbytes(2000)
    return ftyp + meta + mdat, "heic"


def make_mov() -> tuple[bytes, str]:
    ftyp = struct.pack(">I", 20) + b"ftyp" + b"qt  " + bytes(4) + b"qt  "
    moov = struct.pack(">I", 108) + b"moov" + struct.pack(">I", 100) + b"mvhd" + bytes(92)
    mdat = struct.pack(">I", 3008) + b"mdat" + _rng(32).randbytes(3000)
    return ftyp + moov + mdat, "mov"


def make_xlsx() -> tuple[bytes, str]:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/sharedStrings.xml", "<sst><si><t>Budget</t></si></sst>")
    return buf.getvalue(), "xlsx"


def make_epub() -> tuple[bytes, str]:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("OEBPS/chapter1.xhtml", "<html><body>Once upon a time</body></html>" * 20)
    return buf.getvalue(), "epub"


MORE_BUILDERS = {
    "tif": lambda: make_tiff("tif"), "cr2": lambda: make_tiff("cr2"), "nef": lambda: make_tiff("nef"),
    "arw": lambda: make_tiff("arw"), "dng": lambda: make_tiff("dng"), "orf": lambda: make_tiff("orf"),
    "pef": lambda: make_tiff("pef"), "raf": make_raf, "heic": make_heic, "mov": make_mov,
    "mkv": make_mkv, "webm": lambda: make_mkv(True), "wmv": make_asf, "wma": lambda: make_asf(False),
    "flv": make_flv, "ts": make_ts, "m2ts": lambda: make_ts(True), "psd": make_psd, "aiff": make_aiff,
    "mid": make_midi, "iso": make_iso, "ttf": make_ttf, "otf": lambda: make_ttf(True), "rtf": make_rtf,
    "xlsx": make_xlsx, "epub": make_epub,
}
