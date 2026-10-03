"""Byte-exact sample files, built here so tests know what truth is.

Everything is assembled from structure rather than checked into the repo
as an opaque blob, so a test failure points at a specific field.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(
        ">I", zlib.crc32(ctype + data) & 0xFFFFFFFF
    )


def make_png(width: int = 64, height: int = 48, colour: bytes = b"\x20\x60\xd0") -> bytes:
    out = io.BytesIO()
    out.write(b"\x89PNG\r\n\x1a\n")
    out.write(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    raw = b"".join(b"\x00" + colour * width for _ in range(height))
    out.write(_png_chunk(b"IDAT", zlib.compress(raw, 6)))
    out.write(_png_chunk(b"IEND", b""))
    return out.getvalue()


# --------------------------------------------------------------------------
# JPEG (structurally valid: SOI, segments, scan, EOI)
# --------------------------------------------------------------------------


def _jpeg_seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def make_jpeg(width: int = 32, height: int = 32) -> bytes:
    out = bytearray(b"\xff\xd8")
    out += _jpeg_seg(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00")
    out += _jpeg_seg(0xDB, bytes([0x00]) + bytes(range(1, 65)))
    sof = struct.pack(">BHHB", 8, height, width, 1) + bytes([1, 0x11, 0])
    out += _jpeg_seg(0xC0, sof)
    out += _jpeg_seg(0xC4, bytes([0x00]) + bytes([0] * 16) + bytes([0] * 16))
    out += _jpeg_seg(0xDA, bytes([1, 1, 0x00, 0, 63, 0]))
    out += bytes([0x54, 0xFF, 0x00, 0x7F, 0x22, 0x11, 0x33, 0x44, 0x55, 0x66, 0x77])
    out += b"\xff\xd9"
    return bytes(out)


# --------------------------------------------------------------------------
# ZIP (real, via zipfile) and a docx-shaped one
# --------------------------------------------------------------------------


def make_zip(entries: int = 3) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(entries):
            zf.writestr(f"notes/file{i}.txt", f"content of entry {i}\n" * (i + 1))
    return buf.getvalue()


def make_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        zf.writestr("word/document.xml", '<?xml version="1.0"?><document/>' * 40)
    return buf.getvalue()


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------


def make_pdf(pages: int = 2) -> bytes:
    objs: list[bytes] = []
    kids = " ".join(f"{4 + i} 0 R" for i in range(pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i in range(pages):
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + i} 0 R >>".encode()
        )
        stream = f"BT /F1 24 Tf 72 700 Td (page {i}) Tj ET".encode()
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF".encode()
    return bytes(out)


# --------------------------------------------------------------------------
# SQLite (header declares exact page geometry)
# --------------------------------------------------------------------------


def make_sqlite(pages: int = 6) -> bytes:
    page_size = 4096
    header = bytearray(100)
    header[0:16] = b"SQLite format 3\x00"
    struct.pack_into(">H", header, 16, page_size)
    header[18] = 1
    header[19] = 1
    header[20] = 0
    header[21] = 64
    header[22] = 32
    header[23] = 32
    struct.pack_into(">I", header, 24, 1)
    struct.pack_into(">I", header, 28, pages)
    struct.pack_into(">I", header, 32, 0)
    struct.pack_into(">I", header, 36, 0)
    struct.pack_into(">I", header, 40, 4)
    struct.pack_into(">I", header, 44, 4)
    struct.pack_into(">I", header, 56, 1)
    struct.pack_into(">I", header, 92, 1)
    struct.pack_into(">I", header, 96, 3045000)
    out = bytearray(header)
    out += b"\x00" * (page_size - len(header))
    for i in range(2, pages + 1):
        page = bytearray(page_size)
        if i == 2:
            struct.pack_into(">HH", page, 0, 5, 0)
        out += page
    return bytes(out)


# --------------------------------------------------------------------------
# RIFF family
# --------------------------------------------------------------------------


def _riff(form: bytes, body: bytes) -> bytes:
    return b"RIFF" + struct.pack("<I", len(form) + len(body)) + form + body


def make_wav(samples: int = 4000) -> bytes:
    data = b"\x00\x01" * samples
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
    return _riff(b"WAVE", fmt + b"data" + struct.pack("<I", len(data)) + data)


def make_avi(frames: int = 3) -> bytes:
    movi = b""
    for _ in range(frames):
        movi += b"00dc" + struct.pack("<I", 4) + b"\x00" * 4
    hdrl = b"LIST" + struct.pack("<I", 4 + len(movi)) + b"movi" + movi
    return _riff(b"AVI ", hdrl)


def make_webp() -> bytes:
    payload = b"VP8L" + struct.pack("<I", 5) + b"\x2f\x00\x00\x00\x00"
    return _riff(b"WEBP", payload)


# --------------------------------------------------------------------------
# MP4 / ISO base media
# --------------------------------------------------------------------------


def _box(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body) + 8) + ctype + body


def make_mp4(payload: int = 2048) -> bytes:
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    mdat = _box(b"mdat", bytes((i * 7) % 251 for i in range(payload)))
    moov = _box(b"moov", _box(b"mvhd", b"\x00" * 100))
    return ftyp + moov + mdat


# --------------------------------------------------------------------------
# BMP / ICO / GIF
# --------------------------------------------------------------------------


def make_bmp(width: int = 8, height: int = 8) -> bytes:
    row = (width * 3 + 3) // 4 * 4
    pixels = bytes((i * 3) % 256 for i in range(row * height))
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    return b"BM" + struct.pack("<IHHI", 14 + len(dib) + len(pixels), 0, 0, 14 + len(dib)) + dib + pixels


def make_ico() -> bytes:
    image = b"\x00" * 40
    entry = struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, len(image), 22)
    return b"\x00\x00\x01\x00\x01\x00" + entry + image


def make_gif() -> bytes:
    out = bytearray(b"GIF89a")
    out += struct.pack("<HH", 1, 1)
    out += bytes([0x80, 0x00, 0x00])
    out += b"\xff\xff\xff" + b"\x00\x00\x00"
    out += b"\x21\xf9\x04\x01\x00\x00\x00\x00"
    out += b"\x2c" + struct.pack("<HHHH", 0, 0, 1, 1) + b"\x00"
    out += b"\x02\x02\x44\x01\x00"
    out += b"\x3b"
    return bytes(out)


# --------------------------------------------------------------------------
# gzip / 7z
# --------------------------------------------------------------------------


def make_gzip(payload: int = 3000) -> bytes:
    import gzip as _gzip

    buf = io.BytesIO()
    with _gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(b"the quick brown fox jumps over the lazy dog\n" * payload)
    return buf.getvalue()


def make_7z() -> bytes:
    next_header = b"\x17\x06\x00\x00\x00"
    out = bytearray(b"7z\xbc\xaf\x27\x1c")
    out += bytes([0x00, 0x04])
    out += b"\x00\x00\x00\x00"
    out += struct.pack("<Q", 0)
    out += struct.pack("<Q", len(next_header))
    out += b"\x00\x00\x00\x00"
    return bytes(out) + next_header


# --------------------------------------------------------------------------
# XML/SVG
# --------------------------------------------------------------------------


def make_svg() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">\n'
        b'  <rect width="10" height="10" fill="#123456"/>\n'
        b"</svg>\n"
    )


ALL_BUILDERS = {
    "png": make_png,
    "jpg": make_jpeg,
    "zip": make_zip,
    "docx": make_docx,
    "pdf": make_pdf,
    "sqlite": make_sqlite,
    "wav": make_wav,
    "avi": make_avi,
    "webp": make_webp,
    "mp4": make_mp4,
    "bmp": make_bmp,
    "ico": make_ico,
    "gif": make_gif,
    "gz": make_gzip,
    "7z": make_7z,
    "svg": make_svg,
}
