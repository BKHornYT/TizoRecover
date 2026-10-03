<p align="center"><img src="packaging/tizorecover.png" width="96" alt="TizoRecover logo"></p>

<h1 align="center">TizoRecover</h1>

<p align="center">Free, open-source recovery for deleted files. Pick a drive, see what was deleted, preview it, get it back.</p>

---

## What it does

1. **Pick a drive.** USB sticks and memory cards are listed first, because that is where recovery works best.
2. **Quick scan** reads the drive's own file table and finds deleted files with their **real names and folders**, usually in seconds.
3. **Deep scan** also searches every free byte and recognises photos, videos, music, documents and archives **by their contents**, even after a format, when no name is left.
4. **Preview before saving:** pictures, video, audio, PDFs, text and Office documents, plus a hex view of anything.
5. Every file gets a status: **Good**, **Partial** (part of it was reused) or **Overwritten**, so you know what is worth saving.
6. **Recover** the files you tick to a folder on *another* drive. TizoRecover never writes to the drive you are recovering from, and refuses to save onto it.

It can also **erase a removable drive** (quick or full), behind a deliberately slow, typed confirmation.

## Download

From the [latest release](../../releases/latest):

| File | For |
| --- | --- |
| `TizoRecover-<version>-setup.exe` | **Windows, recommended.** Installs for your user (no administrator needed), adds a Start menu entry, and updates itself when a new version is out. |
| `TizoRecover-<version>-portable.exe` | Windows, nothing to install. Runs from anywhere, even from another USB stick. |
| `TizoRecover-<version>-x64.zip` | Windows, the unpacked program (window + command line). |
| `TizoRecover-<version>-x86_64.AppImage` | Linux. Opens in your browser; reading a drive needs root: `sudo ./TizoRecover-…AppImage scan /dev/sdb1`. |

USB sticks and memory cards work without administrator rights on Windows; internal drives need you to accept one administrator prompt.

## Erasing a drive

TizoRecover can also wipe a removable drive (never the Windows drive or an internal one):

- **Quick erase** (under a minute): removes the partition table and file tables, so no files, names or folders remain, then formats. File contents could still be found by a deep scan.
- **Full erase**: overwrites every byte, so nothing can be recovered. Takes as long as the drive needs to write itself full (USB sticks: roughly 15–40 MB/s); already-blank areas are skipped.

You type a confirmation phrase, tick a box and wait out a short countdown before it starts. Flash drives keep a few spare blocks only their own chip can reach, so not even a full erase is a guarantee against a forensic lab.

## Supported

| | Quick scan (names, folders) | Deep scan (by content) |
| --- | --- | --- |
| NTFS (Windows drives, big USB disks) | ✅ | ✅ |
| FAT12 / FAT16 / FAT32 (USB sticks, SD cards) | ✅ | ✅ |
| exFAT (newer USB sticks, SD cards) | planned | ✅ |
| ext4 (Linux) | planned | ✅ |
| Disk image files (`.img`, `.dd`, `.raw`) | ✅ | ✅ |

Recognised by content: JPEG, PNG, GIF, BMP, TIFF, WebP, HEIC, ICO, SVG, MP4, MOV, AVI, MP3, WAV, FLAC, OGG, PDF, ZIP (and DOCX/XLSX/PPTX), DOC/XLS, 7z, RAR, GZIP, SQLite, EXE, ELF.

## Honest limits

- **SSDs** (most modern laptops and PCs) erase deleted data on their own within seconds (TRIM). On an SSD there is often nothing left to find. TizoRecover says so instead of pretending.
- Files saved after the deletion may have overwritten the deleted ones. Stop using the drive as soon as you notice something is missing.
- Files found by content (deep scan) lose their original names.

## Command line

```
TizoRecover-cli drives
TizoRecover-cli scan E:                 # quick scan, list what was found
TizoRecover-cli scan E: --deep -o D:\Recovered
TizoRecover-cli scan disk.img --list
```

## Building from source

Python 3.11+ on Windows. The recovery engine uses only the standard library; the window uses [pywebview](https://pywebview.flowrl.com/).

```
pip install pywebview
python -m tizorecover            # the window
python -m tizorecover scan E:    # the command line
python tests/run_all.py          # all test suites
powershell -File packaging\build.ps1   # setup.exe, portable.exe, x64.zip, latest.yml into release\ (needs Inno Setup 6)
bash packaging/build-appimage.sh         # the Linux AppImage + latest-linux.yml
```

The tests build byte-exact NTFS and FAT volumes in code and recover from them, so they need no real disk.

## License

[GPL-3.0](LICENSE). You may use, study, share and change TizoRecover; if you distribute a changed version, it has to stay open source under the same license.
