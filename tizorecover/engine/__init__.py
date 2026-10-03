"""The TizoRecover recovery engine.

Recovering deleted files needs raw access to the volume: once a file is
unlinked, the directory entry is gone and the only remaining trace is the
raw bytes on the device. This package reads volumes as a flat array of
bytes and layers independent recovery strategies on top, so a file can be
found even when no single strategy succeeds. It has no UI code and no
third-party dependencies.
"""

from tizorecover.engine.results import FileCandidate, RecoveryReport
