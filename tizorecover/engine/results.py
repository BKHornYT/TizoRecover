"""Candidate and report types shared by every recovery strategy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum


class Strategy(str, Enum):
    """A recovery strategy that can independently produce candidates."""

    CARVE = "carve"
    FAT = "fat"
    NTFS = "ntfs"
    EXT4 = "ext4"
    LIVE = "live"


class Verdict(str, Enum):
    """Outcome of validating a carved byte range."""

    VALID = "valid"
    PARTIAL = "partial"
    SUSPECT = "suspect"
    INVALID = "invalid"


UNITS = ("B", "KB", "MB", "GB", "TB")


def human_size(size: int | float) -> str:
    """Format a byte count the way a person would read it."""
    value = float(size)
    for unit in UNITS:
        if value < 1024 or unit == UNITS[-1]:
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{size} B"


@dataclass
class FileCandidate:
    """One recovered file, or one fragment of one.

    A candidate is a claim: "the bytes in ``[data_offset, data_offset+size)
    are a ``.jpg`` that used to live at ``original_path``". Claims from
    different strategies are merged by the report, so the same file can be
    described more than once and still be written out once.
    """

    ext: str
    size: int
    data_offset: int
    strategy: Strategy
    name: str | None = None
    original_path: str | None = None
    verdict: Verdict = Verdict.SUSPECT
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    volume: str = ""
    fragment_index: int = 0
    fragment_count: int = 1
    gaps: list[tuple[int, int]] = field(default_factory=list)
    content_hash: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_fragmented(self) -> bool:
        return self.fragment_index > 0 or self.gaps or self.fragment_count > 1

    @property
    def is_complete(self) -> bool:
        return self.verdict is Verdict.VALID and not self.gaps

    @property
    def display_name(self) -> str:
        if self.original_path:
            return self.original_path
        if self.name:
            return self.name
        return f"recovered_{self.data_offset:012x}.{self.ext or 'bin'}"

    def final_name(self) -> str:
        """Name to write to disk, made unique within a directory."""
        if self.original_path:
            return self.original_path
        if self.name:
            return self.name
        return f"recovered_{self.data_offset:012x}.{self.ext or 'bin'}"

    def with_content(self, data: bytes) -> "FileCandidate":
        """Return a copy carrying its own bytes and a content hash."""
        clone = FileCandidate(**{**self.__dict__})
        clone.content_hash = hashlib.sha256(data).hexdigest()
        clone.metadata = dict(self.metadata)
        clone.reasons = list(self.reasons)
        clone.gaps = list(self.gaps)
        clone.metadata["inline_data"] = data
        return clone

    def describe(self) -> str:
        bits = [f"{self.size:,} B", f"offset {self.data_offset:#x}"]
        if self.original_path:
            bits.append(self.original_path)
        elif self.name:
            bits.append(self.name)
        bits.append(f"{self.ext or '?'} via {self.strategy.value}")
        bits.append(f"{self.verdict.value} {self.confidence:.2f}")
        if self.is_fragmented:
            bits.append("fragmented")
        return " | ".join(bits)


@dataclass
class ScanProblem:
    """Something that limited a scan, reported rather than hidden."""

    strategy: Strategy
    message: str
    fatal: bool = False


@dataclass
class RecoveryReport:
    """Everything one run produced: the files and what went wrong."""

    target: str
    volume: str
    filesystem: str
    volume_size: int
    candidates: list[FileCandidate] = field(default_factory=list)
    problems: list[ScanProblem] = field(default_factory=list)
    bytes_scanned: int = 0
    elapsed: float = 0.0
    device: str = ""

    def add(self, candidate: FileCandidate) -> None:
        self.candidates.append(candidate)

    def problem(self, strategy: Strategy, message: str, fatal: bool = False) -> None:
        self.problems.append(ScanProblem(strategy, message, fatal))

    @property
    def total_bytes_recovered(self) -> int:
        return sum(c.size for c in self.candidates)

    def counts_by_ext(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self.candidates:
            counts[c.ext or "?"] = counts.get(c.ext or "?", 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def summary(self) -> str:
        fs = self.filesystem or "unknown"
        lines = [
            f"Target      {self.target}",
            f"Volume      {self.volume} ({self.volume_size:,} bytes)",
            f"Filesystem  {fs}",
            f"Scanned     {self.bytes_scanned:,} bytes in {self.elapsed:.1f}s",
            f"Recovered   {len(self.candidates)} files, {self.total_bytes_recovered:,} bytes",
        ]
        if self.problems:
            lines.append("Problems:")
            lines.extend(f"  - {p.strategy.value}: {p.message}" for p in self.problems)
        return "\n".join(lines)
