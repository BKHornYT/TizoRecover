"""Raw volume access.

Every strategy in this package reads the volume as a flat byte array, so
this module is the only place that knows whether those bytes come from a
disk image, a block device, or a windowed slice of one.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import BinaryIO

_HAS_PREAD = hasattr(os, "pread")
UNKNOWN_SIZE_CAP = 1 << 40

DEFAULT_CHUNK = 8 * 1024 * 1024


class VolumeAccessError(Exception):
    """The volume exists but cannot be read at the byte level."""


class BlockReader:
    """Read-only, randomly addressable view of a volume."""

    def __init__(self, size: int, label: str = "") -> None:
        self.size = size
        self.label = label

    def read(self, offset: int, length: int) -> bytes:
        raise NotImplementedError

    def read_at(self, offset: int, length: int) -> bytes:
        """Like read, but clamps and zero-pads instead of raising."""
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        data = self.read(offset, length)
        if len(data) < length:
            data += b"\x00" * (length - len(data))
        return data

    def chunks(self, chunk: int = DEFAULT_CHUNK, start: int = 0, end: int | None = None):
        """Yield ``(offset, data)`` sequentially, aligned to ``chunk``."""
        end = self.size if end is None else min(end, self.size)
        pos = start
        while pos < end:
            want = min(chunk, end - pos)
            data = self.read_at(pos, want)
            if not data:
                return
            yield pos, data
            pos += want

    def close(self) -> None:
        pass

    def __enter__(self) -> "BlockReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class FileBlockReader(BlockReader):
    """A volume stored in an image file, or a directory's own bytes."""

    def __init__(self, path: str, label: str = "") -> None:
        self.path = path
        self._fh: BinaryIO = open(path, "rb", buffering=0)
        self._lock = threading.Lock()
        super().__init__(os.fstat(self._fh.fileno()).st_size, label or path)

    def read(self, offset: int, length: int) -> bytes:
        """Read at an offset without disturbing anyone else's position.

        ``os.pread`` does not exist on Windows, so the seek and the read have
        to be done by hand there. The lock keeps two readers of the same handle
        from stepping on each other's position.
        """
        if offset < 0 or length <= 0:
            return b""
        out = bytearray()
        fd = self._fh.fileno()
        with self._lock:
            while len(out) < length:
                if _HAS_PREAD:
                    block = os.pread(fd, length - len(out), offset + len(out))
                else:
                    self._fh.seek(offset + len(out))
                    block = self._fh.read(length - len(out))
                if not block:
                    break
                out += block
        return bytes(out)

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OVERLAPPED = 0x40000000
_INVALID_HANDLE_VALUE = -1
_ERROR_HANDLE_EOF = 38
_ERROR_OPERATION_ABORTED = 995
_ERROR_IO_PENDING = 997
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF

# A volume handle only accepts reads that are a whole number of sectors.
_SECTOR = 512

# CTL_CODE(FILE_DEVICE_DISK, 0x17, METHOD_BUFFERED, FILE_READ_ACCESS): the only
# reliable way to learn how big a volume is. GetFileSizeEx reports 0 for one.
_IOCTL_DISK_GET_LENGTH_INFO = 0x0007005D

_TOKEN_ADJUST_PRIVILEGES = 0x0020
_TOKEN_QUERY = 0x0008
_SE_PRIVILEGE_ENABLED = 0x0002
_ERROR_NOT_ALL_ASSIGNED = 1300

_WIN_ERRORS = {
    1: "the device does not support raw reads; a network share, a virtual disk "
       "or a container layer has no raw volume behind it",
    2: "there is no such volume",
    3: "there is no such volume",
    5: "access was denied",
    32: "another program is holding the volume open exclusively",
    50: "the device does not support raw reads; a network share, a virtual disk "
        "or a container layer has no raw volume behind it",
    87: "that path is not a volume",
}


def _winerror_text(code: int) -> str:
    return _WIN_ERRORS.get(code, f"Windows error {code}")


def _enable_manage_volume_privilege() -> None:
    """Turn on ``SeManageVolumePrivilege``, which is what raw reads need.

    Administrators have the privilege in their token but not enabled, so
    ``CreateFile`` on a volume fails with ERROR_ACCESS_DENIED until it is.
    Best effort: a failure here just means the open below reports the truth.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD),
                    ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                              wintypes.BOOL, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                   ctypes.POINTER(LUID)]
        advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
        advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                                   ctypes.POINTER(TOKEN_PRIVILEGES),
                                                   wintypes.DWORD, ctypes.c_void_p,
                                                   ctypes.c_void_p]
        advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            _TOKEN_ADJUST_PRIVILEGES | _TOKEN_QUERY,
            False,
            ctypes.byref(token),
        ):
            return
        try:
            privileges = TOKEN_PRIVILEGES()
            privileges.PrivilegeCount = 1
            privileges.Privileges[0].Luid = LUID()
            if not advapi32.LookupPrivilegeValueW(
                None, "SeManageVolumePrivilege",
                ctypes.byref(privileges.Privileges[0].Luid),
            ):
                return
            privileges.Privileges[0].Attributes = _SE_PRIVILEGE_ENABLED
            ctypes.set_last_error(0)
            advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges),
                                           0, None, None)
            if ctypes.get_last_error() == _ERROR_NOT_ALL_ASSIGNED:
                return
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        return


def _probe_size(fd: int, path: str) -> int:
    """Best effort at the size of a raw POSIX device, 0 when it cannot be told."""
    for attempt in (lambda: os.lseek(fd, 0, os.SEEK_END),
                    lambda: os.fstat(fd).st_size):
        try:
            size = int(attempt())
        except (OSError, ValueError):
            continue
        if size > 0:
            return size
    return 0


def _windows_volume_size(handle, path: str) -> int:
    r"""Size of a Windows volume, from the handle and then from the drive letter.

    ``GetFileSizeEx`` reports 0 for a volume, so the disk IOCTL is the primary
    answer and ``GetDiskFreeSpaceEx`` is the fallback.
    """
    import ctypes
    from ctypes import wintypes

    try:
        class GET_LENGTH_INFORMATION(ctypes.Structure):
            _fields_ = [("Length", ctypes.c_longlong)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD),
                                             ctypes.c_void_p]
        kernel32.DeviceIoControl.restype = wintypes.BOOL
        info = GET_LENGTH_INFORMATION()
        returned = wintypes.DWORD(0)
        if kernel32.DeviceIoControl(handle, _IOCTL_DISK_GET_LENGTH_INFO, None, 0,
                                    ctypes.byref(info), ctypes.sizeof(info),
                                    ctypes.byref(returned), None):
            if info.Length > 0:
                return int(info.Length)
    except Exception:
        pass

    if not path.startswith("\\\\.\\") or not path[4:5].isalpha():
        return 0
    try:
        free_to_caller = ctypes.c_ulonglong(0)
        total = ctypes.c_ulonglong(0)
        total_free = ctypes.c_ulonglong(0)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR,
                                                 ctypes.POINTER(ctypes.c_ulonglong),
                                                 ctypes.POINTER(ctypes.c_ulonglong),
                                                 ctypes.POINTER(ctypes.c_ulonglong)]
        kernel32.GetDiskFreeSpaceExW.restype = wintypes.BOOL
        if kernel32.GetDiskFreeSpaceExW(f"{path[4]}:\\", ctypes.byref(free_to_caller),
                                        ctypes.byref(total), ctypes.byref(total_free)):
            return int(total.value)
    except Exception:
        pass
    return 0


class WindowsVolume:
    r"""A Windows volume opened for raw reads, straight through the Win32 API.

    ``os.open`` cannot do this. The Windows CRT opens with no share mode at
    all, so it demands exclusive access to a volume that the operating system
    is itself holding open, and the open fails even for an administrator. A
    descriptor from ``open_osfhandle`` is no better: reads through it fail
    with ``EINVAL``. So the handle is kept as a handle.

    Reads are overlapped with an explicit offset rather than sequential.
    A volume handle's file pointer is not dependable for this: seeking with
    ``SetFilePointerEx`` reports success and the read that follows then
    returns nothing, so the only way to land on an offset is to name the
    offset in the ``OVERLAPPED`` structure. That also means concurrent readers
    cannot step on each other.
    """

    _SEEK_CHUNK = 16 * 1024 * 1024

    def __init__(self, path: str) -> None:
        import ctypes
        from ctypes import wintypes

        self.path = path
        self._lock = threading.Lock()
        self._ctypes = ctypes
        self._buffer_size = 1 << 20
        self._buffer = ctypes.create_string_buffer(self._buffer_size)

        _enable_manage_volume_privilege()

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                         wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD,
                                         wintypes.HANDLE]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.c_void_p, ctypes.c_void_p]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                                  ctypes.POINTER(wintypes.DWORD),
                                                  wintypes.BOOL]
        kernel32.GetOverlappedResult.restype = wintypes.BOOL
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                          wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32 = kernel32
        self._dword = wintypes.DWORD
        self._byref = ctypes.byref
        self._last_error = ctypes.get_last_error
        self._clear_error = ctypes.set_last_error

        handle = kernel32.CreateFileW(
            path, _GENERIC_READ, _FILE_SHARE_READ | _FILE_SHARE_WRITE, None,
            _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OVERLAPPED, None,
        )
        if handle == _INVALID_HANDLE_VALUE or handle is None:
            code = self._last_error()
            raise OSError(code, _winerror_text(code), path)
        self._handle = handle

        self._event = kernel32.CreateEventW(None, False, False, None)
        if self._event == _INVALID_HANDLE_VALUE or self._event is None:
            code = self._last_error()
            kernel32.CloseHandle(handle)
            raise OSError(code, "could not create the read event", path)

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p),
                        ("InternalHigh", ctypes.c_void_p),
                        ("Offset", wintypes.DWORD),
                        ("OffsetHigh", wintypes.DWORD),
                        ("hEvent", wintypes.HANDLE)]

        overlapped = OVERLAPPED()
        overlapped.hEvent = self._event
        self._overlapped = overlapped

    def read(self, offset: int, length: int) -> bytes:
        """Read exactly ``length`` bytes from ``offset``, sector aligned.

        A volume handle rejects a read that is not a whole number of sectors
        with ERROR_INVALID_PARAMETER, so a 4-byte read for an MFT signature
        fails outright. The read is widened to sector boundaries and the
        wanted slice is cut back out of it.
        """
        if offset < 0 or length <= 0:
            return b""
        start = offset - (offset % _SECTOR)
        skip = offset - start
        span = skip + length
        span = -(-span // _SECTOR) * _SECTOR
        data = self._read_aligned(start, span)
        if not data:
            return b""
        return data[skip:skip + length]

    def _read_aligned(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0:
            return b""
        out = bytearray()
        want_buffer = min(length, self._SEEK_CHUNK)
        if want_buffer > self._buffer_size:
            self._buffer = self._ctypes.create_string_buffer(want_buffer)
            self._buffer_size = want_buffer
        with self._lock:
            while len(out) < length:
                want = min(length - len(out), self._buffer_size)
                position = offset + len(out)
                overlapped = self._overlapped
                overlapped.Internal = None
                overlapped.InternalHigh = None
                overlapped.Offset = position & 0xFFFFFFFF
                overlapped.OffsetHigh = (position >> 32) & 0xFFFFFFFF
                self._clear_error(0)
                queued = self._k32.ReadFile(self._handle, self._buffer, want,
                                            None, self._byref(overlapped))
                code = self._last_error()
                if not queued and code != _ERROR_IO_PENDING:
                    raise OSError(code, _winerror_text(code), self.path)
                waited = self._k32.WaitForSingleObject(self._event, _INFINITE)
                if waited != _WAIT_OBJECT_0:
                    raise OSError(code, f"raw read did not finish (wait={waited})",
                                  self.path)
                transferred = self._dword(0)
                self._clear_error(0)
                if not self._k32.GetOverlappedResult(self._handle, self._byref(overlapped),
                                                     self._byref(transferred), False):
                    code = self._last_error()
                    if code in (_ERROR_HANDLE_EOF, _ERROR_OPERATION_ABORTED):
                        break
                    raise OSError(code, _winerror_text(code), self.path)
                if transferred.value == 0:
                    break
                out += self._buffer.raw[:transferred.value]
        return bytes(out)

    def size(self) -> int:
        return _windows_volume_size(self._handle, self.path)

    def close(self) -> None:
        try:
            self._k32.CloseHandle(self._handle)
        except Exception:
            pass


class DeviceBlockReader(BlockReader):
    """A raw block device or a Windows volume handle (``\\\\.\\C:``)."""

    def __init__(self, path: str, label: str = "") -> None:
        self.path = path
        self._volume: WindowsVolume | None = None
        self._fd: int | None = None
        try:
            if os.name == "nt" and path.startswith("\\\\.\\"):
                self._volume = WindowsVolume(path)
                size = self._volume.size()
            else:
                self._fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                size = _probe_size(self._fd, path)
        except OSError as exc:
            raise VolumeAccessError(
                f"{path} could not be opened for raw reading: "
                f"{_winerror_text(exc.errno or 0) if os.name == 'nt' and path.startswith(chr(92) * 2 + '.' + chr(92)) else exc}. "
                f"Deleted files only exist in the volume's raw bytes, so this "
                f"needs a real local disk: run the app as administrator on "
                f"Windows (raw volume reads are refused to a normal process) and "
                f"check the folder is not on a network share, a virtual disk or "
                f"a container layer, none of which have one."
            ) from exc
        self._lock = threading.Lock()
        self.size_known = size > 0
        super().__init__(size or UNKNOWN_SIZE_CAP, label or path)

    def read(self, offset: int, length: int) -> bytes:
        """Read at an offset, seeking by hand where ``os.pread`` is missing.

        On Windows there is no ``os.pread``, and a volume handle is not
        seekable to arbitrary offsets with the usual semantics, so the seek and
        the read are paired under one lock.
        """
        if offset < 0 or length <= 0:
            return b""
        if self._volume is not None:
            return self._volume.read(offset, length)
        assert self._fd is not None
        out = bytearray()
        with self._lock:
            while len(out) < length:
                want = length - len(out)
                if _HAS_PREAD:
                    block = os.pread(self._fd, want, offset + len(out))
                else:
                    os.lseek(self._fd, offset + len(out), os.SEEK_SET)
                    block = os.read(self._fd, want)
                if not block:
                    break
                out += block
        return bytes(out)

    def close(self) -> None:
        if self._volume is not None:
            self._volume.close()
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass


class WindowBlockReader(BlockReader):
    """A sub-range of another reader, addressed in parent coordinates."""

    def __init__(self, parent: BlockReader, start: int, end: int, label: str = "") -> None:
        self.parent = parent
        self.start = start
        super().__init__(max(0, end - start), label or f"{parent.label}+{start:#x}")

    def read(self, offset: int, length: int) -> bytes:
        return self.parent.read(self.start + offset, length)

    def close(self) -> None:
        self.parent.close()


def open_source(path: str) -> BlockReader:
    """Open an image file or a raw device, whichever ``path`` names."""
    if os.path.isdir(path):
        raise VolumeAccessError(
            f"{path} is a directory; raw bytes require the volume it lives on"
        )
    if os.path.isfile(path):
        return FileBlockReader(path)
    if not os.path.exists(path):
        raise VolumeAccessError(
            f"{path} is not a readable volume. Deleted files live in the volume's raw "
            f"bytes, so this needs administrator rights (Windows) or root (Linux), "
            f"and the volume must be a real disk rather than a network share, a "
            f"virtual disk or a container layer."
        )
    try:
        return DeviceBlockReader(path)
    except VolumeAccessError:
        raise
    except OSError as exc:
        raise VolumeAccessError(
            f"{path} could not be opened for raw reading: {exc}. "
            f"Run the app as administrator (Windows) or with sudo (Linux); "
            f"reading a live volume's raw bytes is not permitted otherwise."
        ) from exc


def windows_volume_path(drive: str) -> str:
    """``C:\\`` -> ``\\\\.\\C:`` for byte-level access."""
    letter = drive.rstrip("\\/")[:1]
    return f"\\\\.\\{letter}:"


def linux_device_for(path: str) -> str | None:
    """Find the block device backing ``path`` via /proc/self/mountinfo."""
    try:
        target = os.stat(path).st_dev
    except OSError:
        return None
    best: tuple[int, str] | None = None
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                fields = line.split()
                if len(fields) < 10:
                    continue
                sep = fields.index("-")
                if sep < 7:
                    continue
                mount_point = fields[4].replace("\\040", " ")
                source = fields[sep + 2] if len(fields) > sep + 2 else ""
                if not source.startswith("/dev/"):
                    continue
                try:
                    if os.stat(mount_point).st_dev != target:
                        continue
                except OSError:
                    continue
                depth = mount_point.rstrip("/").count("/")
                if best is None or depth > best[0]:
                    best = (depth, source)
    except OSError:
        return None
    return best[1] if best else None


def resolve_volume(folder: str) -> tuple[str, str, int]:
    """Map a user-picked folder to the volume that must be read.

    Returns ``(device_path, filesystem_hint, approximate_size)``. On
    Windows the returned path is a ``\\\\.\\X:`` handle. Raises
    ``VolumeAccessError`` with a message meant for a human when the folder
    is on something that has no raw device, e.g. a network share.
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise VolumeAccessError(f"not a folder: {folder}")

    if sys.platform == "win32":
        drive = os.path.splitdrive(folder)[0]
        if not drive:
            raise VolumeAccessError(
                f"{folder} is not on a drive that can be read at the byte level"
            )
        device = windows_volume_path(drive)
        size = 0
        return device, "ntfs", size

    device = linux_device_for(folder)
    if device is None:
        raise VolumeAccessError(
            f"{folder} has no raw block device behind it (network share, "
            f"virtual filesystem, or container layer); deleted files cannot be "
            f"recovered from raw bytes here"
        )
    try:
        size = os.stat(device).st_size
    except OSError:
        size = 0
    return device, "", size
