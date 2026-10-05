"""How likely a found file is to come back intact.

Every candidate gets one of three statuses:

``good``         nothing suggests damage: its clusters are free and, where
                 the format is known, its first bytes are what that format
                 starts with.
``partial``      some of it has been reused or it does not start the way its
                 extension says, so expect a damaged file.
``overwritten``  all of its clusters belong to other files now, or the data
                 reads as zeros (what an SSD returns after TRIM).
"""

from __future__ import annotations

from tizorecover.engine.access import CandidateData, pieces_of
from tizorecover.engine.formats import EXT_FORMATS
from tizorecover.engine.results import FileCandidate, Strategy, Verdict

GOOD = "good"
PARTIAL = "partial"
OVERWRITTEN = "overwritten"

ALIASES = {
    "jpeg": "jpg", "jpe": "jpg", "jfif": "jpg",
    "tiff": "tif", "m4v": "mp4", "m4a": "mp4", "3gp": "mp4", "mov": "mp4", "cr3": "mp4",
    "avif": "mp4", "heic": "mp4", "heif": "mp4",
    "cr2": "tif", "nef": "tif", "arw": "tif", "dng": "tif", "pef": "tif", "srw": "tif",
    "orf": "tif", "rw2": "tif", "webm": "mkv", "wma": "wmv", "otf": "ttf", "aif": "aiff",
    "vsdx": "zip",
    "docx": "zip", "xlsx": "zip", "pptx": "zip", "odt": "zip", "ods": "zip",
    "odp": "zip", "jar": "zip", "apk": "zip", "epub": "zip",
    "xls": "doc", "ppt": "doc", "msg": "doc",
    "db": "sqlite", "sqlite3": "sqlite",
    "dll": "exe", "sys": "exe", "tgz": "gz",
}

CATEGORIES = {
    "image": {"jp2", "j2k", "jxl", "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif",
              "avif", "ico", "svg", "raw", "cr2", "cr3", "nef", "arw", "dng", "orf", "rw2", "psd",
              "pef", "srw", "raf", "x3f", "nrw"},
    "video": {"mpg", "mpeg", "vob", "m1v", "m2v", "dav", "rm", "rmvb", "swf", "mxf", "mp4", "m4v", "mov", "avi", "mkv", "webm", "wmv", "flv", "3gp", "mts", "m2ts",
              "mpg", "mpeg", "ts", "vob", "m4v"},
    "audio": {"amr", "ape", "au", "caf", "mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma", "aiff", "aif", "mid", "midi"},
    "document": {"djvu", "ps", "eps", "pst", "ost", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp",
                 "rtf", "txt", "md", "csv", "html", "htm", "xml", "json", "epub", "pages",
                 "key", "numbers", "log", "ini", "cfg", "yaml", "yml", "vsdx"},
    "archive": {"zip", "rar", "7z", "gz", "tgz", "tar", "bz2", "xz", "zst", "iso", "cab"},
    "code": {"py", "js", "ts", "c", "h", "cpp", "cs", "java", "go", "rs", "php", "rb",
             "sh", "ps1", "bat", "css", "lua", "kt", "swift", "sql"},
    "program": {"dex", "exe", "dll", "msi", "sys", "elf", "apk", "jar", "so"},
}
EXT_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}


def category_of(ext: str) -> str:
    return EXT_CATEGORY.get((ext or "").lower(), "other")


def _magic_ok(data: CandidateData, ext: str) -> bool | None:
    """True/False when the extension names a known format, None otherwise."""
    fmt = EXT_FORMATS.get(ALIASES.get(ext, ext))
    if fmt is None or not fmt.magics:
        return None
    head = data.at(0, 64)
    if not head:
        return False
    back = fmt.back or 0
    return any(head[back:back + len(m)] == m for m in fmt.magics)


def assess(candidate: FileCandidate, src, allocation=None) -> tuple[str, list[str]]:
    """Status and the reasons behind it."""
    notes: list[str] = []
    if candidate.strategy is Strategy.CARVE:
        if candidate.verdict is Verdict.VALID:
            return GOOD, ["structure checked end to end by the carver"]
        return PARTIAL, ["found by signature; structure incomplete or unchecked"]

    data = CandidateData(candidate, src)
    used = 0.0
    if allocation is not None and candidate.metadata.get("inline_data") is None:
        used = allocation.used_fraction(pieces_of(candidate))
    if used >= 0.999:
        return OVERWRITTEN, ["all of its clusters belong to other files now"]

    head = data.at(0, 4096)
    if head and head.count(0) == len(head) and candidate.size > 64:
        if used > 0:
            return OVERWRITTEN, ["partly reused, and the start reads as zeros"]
        notes.append("the start reads as zeros (wiped, or TRIM on an SSD)")
        return OVERWRITTEN, notes

    status = GOOD
    if used > 0:
        status = PARTIAL
        notes.append(f"{used:.0%} of its clusters are in use by other files")
    magic = _magic_ok(data, (candidate.ext or "").lower())
    if magic is False:
        status = PARTIAL
        notes.append(f"does not start like a .{candidate.ext} file")
    elif magic is True:
        notes.append(f"starts like a real .{candidate.ext} file")
    if candidate.metadata.get("compressed"):
        status = PARTIAL
        notes.append("NTFS-compressed; the clusters hold compressed data")
    if candidate.verdict is Verdict.PARTIAL and status == GOOD:
        status = PARTIAL
    if candidate.metadata.get("chain_guessed"):
        notes.append("FAT chain was freed; the layout is a best guess")
    return status, notes
