"""Names for carved files, read from the files themselves (engine/naming.py)."""

from __future__ import annotations

import io
import os
import random
import struct
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine import naming
from tizorecover.engine.drives import image_drive
from tizorecover.engine.session import DEEP, ScanJob
from tests import fsimages, samples

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        failures.append(label)


def reader(blob: bytes):
    return lambda off, n: blob[off:off + n]


def describe(blob: bytes, ext: str):
    return naming.describe(reader(blob), len(blob), ext)


# ------------------------------------------------------------------ builders

def tiff(make: str, model: str, date: str) -> bytes:
    """Little-endian TIFF: IFD0 (Make, Model, ExifIFD) -> Exif IFD (DateTimeOriginal)."""
    strings = [make.encode() + b"\x00", model.encode() + b"\x00", date.encode() + b"\x00"]
    ifd0_off = 8
    ifd0_len = 2 + 3 * 12 + 4
    exif_off = ifd0_off + ifd0_len
    exif_len = 2 + 1 * 12 + 4
    data_off = exif_off + exif_len
    offs = []
    pos = data_off
    for s in strings:
        offs.append(pos)
        pos += len(s)
    out = bytearray(b"II*\x00" + struct.pack("<I", ifd0_off))
    out += struct.pack("<H", 3)
    out += struct.pack("<HHII", 0x010F, 2, len(strings[0]), offs[0])
    out += struct.pack("<HHII", 0x0110, 2, len(strings[1]), offs[1])
    out += struct.pack("<HHII", 0x8769, 4, 1, exif_off)
    out += struct.pack("<I", 0)
    out += struct.pack("<H", 1)
    out += struct.pack("<HHII", 0x9003, 2, len(strings[2]), offs[2])
    out += struct.pack("<I", 0)
    for s in strings:
        out += s
    return bytes(out)


def jpeg_with_exif(make="Canon", model="Canon EOS R6", date="2024:05:01 14:32:10") -> bytes:
    body = samples.make_jpeg()
    t = tiff(make, model, date)
    app1 = b"\xff\xe1" + struct.pack(">H", 2 + 6 + len(t)) + b"Exif\x00\x00" + t
    return body[:2] + app1 + body[2:]


def id3(title: str, artist: str) -> bytes:
    def frame(fid, text):
        data = b"\x03" + text.encode("utf-8")
        return fid + struct.pack(">I", len(data)) + b"\x00\x00" + data
    frames = frame(b"TIT2", title) + frame(b"TPE1", artist)
    n = len(frames)
    size = bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])
    return b"ID3\x03\x00\x00" + size + frames + b"\xff\xfb\x90\x00" + b"\x00" * 400


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def mp4(created_unix: int | None, title: str | None = None, artist: str | None = None, moov_last=True) -> bytes:
    ct = (created_unix + 2082844800) if created_unix else 0
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">II", ct, ct) + b"\x00" * 88)
    ilst_items = b""
    for key, val in ((b"\xa9nam", title), (b"\xa9ART", artist)):
        if val:
            data = box(b"data", struct.pack(">II", 1, 0) + val.encode())
            ilst_items += box(key, data)
    udta = box(b"udta", box(b"meta", b"\x00\x00\x00\x00" + box(b"ilst", ilst_items))) if ilst_items else b""
    moov = box(b"moov", mvhd + udta)
    ftyp = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    mdat = box(b"mdat", os.urandom(300_000))
    return ftyp + (mdat + moov if moov_last else moov + mdat)


def docx(title: str, modified="2025-11-03T09:15:00Z") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("docProps/core.xml",
                   f'<cp:coreProperties xmlns:dc="x" xmlns:dcterms="y"><dc:title>{title}</dc:title>'
                   f'<dcterms:modified xsi:type="dcterms:W3CDTF">{modified}</dcterms:modified></cp:coreProperties>')
    return buf.getvalue()


# ------------------------------------------------------------------ tests

def test_readers():
    print("names from content")
    name, ts = describe(jpeg_with_exif(), "jpg")
    check("photo: date + camera", name == "Photo 2024-05-01 14.32.10 (Canon EOS R6)", str(name))
    check("photo: date becomes modified", ts == 1714573930.0, str(ts))
    name, _ = describe(jpeg_with_exif("NIKON CORPORATION", "D750"), "jpg")
    check("photo: make added when the model lacks it", name and name.endswith("(Nikon D750)"), str(name))
    check("photo without EXIF: no name", describe(samples.make_jpeg(), "jpg") == (None, None))
    raw = tiff("SONY", "ILCE-7M3", "2023:12:24 18:00:01") + b"\x00" * 1000
    name, _ = describe(raw, "arw")
    check("RAW (TIFF) photo", name == "Photo 2023-12-24 18.00.01 (Sony ILCE-7M3)", str(name))

    name, _ = describe(id3("Black Glass Bass", "bkhorn"), "mp3")
    check("MP3: artist - title", name == "bkhorn - Black Glass Bass", str(name))

    name, ts = describe(mp4(1717000000), "mp4")
    check("video: creation date (moov at the end)", name == "Video 2024-05-29 16.26.40", str(name))
    name, _ = describe(mp4(1717000000, moov_last=False), "mov")
    check("video: moov first", name == "Video 2024-05-29 16.26.40", str(name))
    name, _ = describe(mp4(None, "Holiday song", "Ola"), "m4a")
    check("M4A: artist - title from tags", name == "Ola - Holiday song", str(name))
    check("video with no date or tags: no name", describe(mp4(None), "mp4") == (None, None))

    pdf = b"%PDF-1.4\n1 0 obj << /Title (Budget 2026) /CreationDate (D:20260115093000) >> endobj\n%%EOF"
    name, ts = describe(pdf, "pdf")
    check("PDF title", name == "Budget 2026", str(name))
    check("PDF date", ts is not None)
    hexpdf = b"%PDF-1.7\n<< /Title <FEFF004E00E6007200620061006B006B00650072> >>\n%%EOF"
    check("PDF UTF-16 title", describe(hexpdf, "pdf")[0] == "Nærbakker", str(describe(hexpdf, "pdf")[0]))
    check("PDF junk title ignored", describe(b"%PDF-1.4\n<< /Title (about blank) >>", "pdf")[0] is None)

    name, _ = describe(docx("Søknad om permisjon"), "docx")
    check("DOCX title", name == "Søknad om permisjon", str(name))
    name, _ = describe(docx(""), "docx")
    check("DOCX without title: dated", name == "Document 2025-11-03 09.15.00", str(name))
    check("odd characters cleaned", "/" not in (describe(docx("a/b:c?"), "docx")[0] or "/"))


def test_never_raises():
    print("damaged input never raises")
    rng = random.Random(5)
    seeds = {"jpg": jpeg_with_exif(), "mp3": id3("t", "a"), "mp4": mp4(1717000000, "x"), "pdf": b"%PDF-1.4 /Title (x)",
             "docx": docx("x"), "arw": tiff("A", "B", "2020:01:01 00:00:00")}
    bad = 0
    for ext, blob in seeds.items():
        for _ in range(300):
            buf = bytearray(blob)
            for _ in range(rng.randint(1, 12)):
                buf[rng.randrange(len(buf))] = rng.randrange(256)
            if rng.random() < 0.3:
                buf = buf[:rng.randrange(1, len(buf))]
            try:
                describe(bytes(buf), ext)
            except Exception as exc:  # noqa: BLE001
                bad += 1
                print("    ", ext, repr(exc))
    check("1800 damaged files, no exception", bad == 0, str(bad))


def test_scan_names_carved_photo():
    print("deep scan names a carved photo")
    # No file system at all (a wiped card): only carving can find the photo.
    raw = bytearray(4 << 20)
    photo = jpeg_with_exif()
    raw[1 << 20:(1 << 20) + len(photo)] = photo
    fh = tempfile.NamedTemporaryFile(suffix=".img", delete=False)
    fh.write(bytes(raw))
    fh.close()
    job = ScanJob(image_drive(fh.name), DEEP).start()
    job.wait(60)
    names = [it.candidate.name for it in job.snapshot() if it.candidate.strategy.value == "carve"]
    check("carved photo named from EXIF", any(n and n.startswith("Photo 2024-05-01 14.32.10") for n in names), str(names[:4]))
    job.close()
    os.unlink(fh.name)


def main() -> int:
    test_readers()
    test_never_raises()
    test_scan_names_carved_photo()
    print()
    if failures:
        print(f"{len(failures)} naming checks FAILED")
        return 1
    print("all naming checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
