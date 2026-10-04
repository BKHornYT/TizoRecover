<p align="center"><img src="packaging/tizorecover.png" width="96" alt="TizoRecover logo"></p>

<h1 align="center">TizoRecover</h1>

<p align="center">Free, open-source recovery for deleted files. Pick a drive, see what was deleted, preview it, get it back.</p>

---

## What it does

1. **Pick a drive** (disks with their partitions; USB sticks and memory cards first, because that is where recovery works best) and press **Search for lost data**.
2. **All recovery methods** (the default) first reads the drive's own file table, which finds deleted files with their **real names and folders** in seconds, then searches all free space and recognises photos, videos, music, documents and archives **by their contents**, even after a format. **Quick scan** does only the first part.
3. Watch it work: progress, speed, time left and live counts per file type. You can **look through what has been found while it is still scanning**.
4. **Stop any time and resume later.** Scans save themselves every minute; the drive list offers *Resume scan* (or *Open last results* for a finished scan). A long scan of a big hard drive no longer has to happen in one go.
5. Review the results the way the drive had them (**Deleted or lost**, with folders) or by type (**Reconstructed**, found by content), with search, filters and a preview of pictures, video, audio, PDFs, text and Office documents, plus a hex view of anything.
6. Every file shows its **recovery chances**: **High**, **Average** (part of it may have been reused) or **Low** (overwritten), so you know what is worth saving.
7. **Quick Look**: press Space (or double-click) for a full-window preview and step through files with the arrow keys. Thumbnails show right in the list; camera RAW files, music with album art and videos the preview cannot play show the picture stored inside them.
8. **Lost partitions and "undo a format"**: *Find lost partitions* looks for file systems that were deleted from the partition table or formatted over (NTFS, FAT32, exFAT through their backup boot sectors; Linux ext through backup superblocks). A drive that was quick-formatted can be scanned *as it was before*, names and folders included. 
9. **Recover** the files and folders you tick to a folder on *another* drive. TizoRecover never writes to the drive you are recovering from, refuses to save onto it, and checks the destination has room.

10. **Gallery**: every picture and video found, big, in one place, newest first. Click one to see it full size and step through with the arrow keys; tick what you want back.
11. **Fix a drive**: drive not showing up? *Watch while I plug it in* follows the drive from the plug to a drive letter and says where it gets stuck (no power, a failing USB 3 connection, a driver, no drive letter, no partitions). *Check my drives* finds offline disks, missing letters, unreadable (RAW) drives, failed connections and USB power saving, and fixes what it safely can, asking first. It never formats or initializes anything.
12. **Eject** USB drives and memory cards from the drive list, or right after recovering.
13. **Saved scans**: every scan saves itself; one page lists them all, with where they are kept.

TizoRecover always runs as administrator (Windows asks when it starts): deleted files only exist in a drive's raw bytes, and reading those needs it. On Linux it asks for the root password the same way.

Under *Disk tools* it can also **erase a removable drive** (quick or full), behind a deliberately slow, typed confirmation.

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
| exFAT (newer USB sticks, SD cards) | ✅ | ✅ |
| ext2/3/4 (Linux, Raspberry Pi, Android cards) | ✅ (deleted files from the journal) | ✅ |
| Disk image files (`.img`, `.dd`, `.raw`) | ✅ | ✅ |

Recognised by content (about 60 types, each sized exactly where the format allows and named by what is inside):

- **Photos:** JPEG, PNG, GIF, BMP, WebP, HEIC, AVIF, TIFF, PSD, ICO, SVG, and camera RAW: CR2, CR3, NEF, ARW, DNG, PEF, SRW, ORF, RW2, RAF
- **Video:** MP4, MOV, M4V, 3GP, MKV, WebM, AVI, WMV, FLV, MPEG-TS / M2TS (camcorders)
- **Audio:** MP3, M4A, WAV, FLAC, OGG, WMA, AIFF, MIDI
- **Documents:** PDF, DOCX, XLSX, PPTX, VSDX, ODT/ODS/ODP, EPUB, DOC/XLS/PPT, RTF, SQLite
- **Archives and more:** ZIP, 7z, RAR, GZIP, ISO images, APK, JAR, EXE/DLL, ELF, TTF/OTF fonts

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
