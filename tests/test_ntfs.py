"""NTFS undelete tests against a hand-built volume."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tizorecover.engine.formats import ByteSourceView
from tizorecover.engine.fs import ntfs
from tizorecover.engine.results import Strategy
from tizorecover.engine.access import read_all
from tests import fsimages, samples


def _scan(builder: fsimages.NtfsBuilder):
    image = builder.build()
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        from tizorecover.engine.blockdev import FileBlockReader

        reader = FileBlockReader(path, "ntfs-test")
        try:
            src = ByteSourceView(reader)
            found = list(ntfs.recover_ntfs(src, "ntfs-test"))
            for c in found:
                c.metadata["inline_data"] = read_all(c, src)
            return found, image
        finally:
            reader.close()
    finally:
        os.unlink(path)


def test_boot_sector():
    print("ntfs: boot sector parsed")
    boot = None
    image = fsimages.NtfsBuilder().build()
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        from tizorecover.engine.blockdev import FileBlockReader

        r = FileBlockReader(path)
        try:
            boot = ntfs.parse_boot_sector(ByteSourceView(r))
        finally:
            r.close()
    finally:
        os.unlink(path)
    ok = boot is not None and boot.cluster_size == 4096 and boot.mft_record_size == 1024
    print(f"  {'ok  ' if ok else 'FAIL'} cluster={boot.cluster_size if boot else '?'} "
          f"record={boot.mft_record_size if boot else '?'} serial={boot.serial if boot else '?':#x}")
    return [] if ok else ["boot sector not parsed"]


def test_named_contiguous_file():
    print("ntfs: deleted file recovers with its name and path")
    b = fsimages.NtfsBuilder()
    photos = b.add_dir("Photos")
    payload = samples.make_png(200, 200)
    b.add_deleted_file("holiday.png", payload, parent_index=photos)
    found, _ = _scan(b)
    hits = [c for c in found if c.name == "holiday.png"]
    if not hits:
        print(f"  FAIL not found; got {[(c.name, c.original_path) for c in found]}")
        return ["named file missing"]
    c = hits[0]
    exact = c.metadata["inline_data"] == payload
    ok = exact and c.original_path == "Photos/holiday.png" and c.strategy is Strategy.NTFS
    print(f"  {'ok  ' if ok else 'FAIL'} name={c.name} path={c.original_path!r} "
          f"size={c.size} bytes_match={exact} conf={c.confidence}")
    print(f"       reasons: {c.reasons}")
    return [] if ok else ["named file wrong"]


def test_resident_file():
    print("ntfs: resident (small) deleted file recovers from the record")
    b = fsimages.NtfsBuilder()
    text = b"to be or not to be, that is the question"
    b.add_deleted_file("shakespeare.txt", text, resident=True)
    found, _ = _scan(b)
    hits = [c for c in found if c.name == "shakespeare.txt"]
    if not hits:
        return ["resident file missing"]
    c = hits[0]
    ok = c.metadata["inline_data"] == text and c.metadata["resident"] is True
    print(f"  {'ok  ' if ok else 'FAIL'} size={c.size} resident={c.metadata['resident']} "
          f"match={c.metadata['inline_data'] == text}")
    return [] if ok else ["resident file wrong"]


def test_fragmented_file_reports_gaps():
    print("ntfs: file split across extents is flagged as fragmented")
    b = fsimages.NtfsBuilder()
    payload = samples.make_jpeg(200, 200)
    b.add_deleted_file("split.jpg", payload, extents=3)
    found, _ = _scan(b)
    hits = [c for c in found if c.name == "split.jpg"]
    if not hits:
        return ["fragmented file missing"]
    c = hits[0]
    ok = c.is_fragmented and len(c.metadata["runlist"]) == 3
    print(f"  {'ok  ' if ok else 'FAIL'} extents={len(c.metadata['runlist'])} "
          f"gaps={c.gaps} fragment_count={c.fragment_count} size={c.size} of {len(payload)}")
    print(f"       reasons: {c.reasons}")
    return [] if ok else ["fragmentation not reported"]


def test_live_files_excluded():
    print("ntfs: files still in use are not reported as deleted")
    b = fsimages.NtfsBuilder()
    b.add_live_file("present.txt", b"still here\n")
    b.add_deleted_file("gone.txt", b"deleted\n")
    found, _ = _scan(b)
    names = [c.name for c in found]
    ok = names == ["gone.txt"]
    print(f"  {'ok  ' if ok else 'FAIL'} recovered={names}")
    return [] if ok else ["live file leaked into results"]


def test_many_files():
    print("ntfs: a folder full of deletions all come back")
    b = fsimages.NtfsBuilder()
    docs = b.add_dir("Documents")
    expected = {}
    for i in range(6):
        if i % 3 == 0:
            data = samples.make_png(60 + i, 40)
            name = f"image{i}.png"
        elif i % 3 == 1:
            data = b"x" * (500 + i * 37)
            name = f"data{i}.bin"
        else:
            data = samples.make_zip(2)
            name = f"bundle{i}.zip"
        b.add_deleted_file(name, data, parent_index=docs)
        expected[name] = data
    found, _ = _scan(b)
    failures = []
    by_name = {c.name: c for c in found}
    for name, data in expected.items():
        c = by_name.get(name)
        if c is None:
            print(f"  FAIL {name} missing")
            failures.append(name)
            continue
        ok = c.metadata["inline_data"] == data
        print(f"  {'ok  ' if ok else 'FAIL'} {name:14s} path={c.original_path!r} size={c.size}")
        if not ok:
            failures.append(name)
    return failures


def _fragmented_builder() -> fsimages.NtfsBuilder:
    """A volume whose $MFT is split across four scattered extents.

    This is the shape of every real NTFS volume: the $MFT is a fragmented file
    and its first extent holds only part of the records. Laying it out
    contiguously, as the builder used to, hid a bug where every record's
    address was computed as ``$MFT start + index * record_size`` and the walk
    therefore ran off the end of the first extent into unrelated disk content
    and reported no deleted files at all.
    """
    builder = fsimages.NtfsBuilder(total_clusters=16384, mft_fragments=4,
                                   mft_fragment_lcns=(2000, 4000, 6000, 8000))
    folder = builder.add_dir("Holiday")
    for index in range(30):
        builder.add_live_file(f"live{index}.txt", b"x" * 100)
    builder.add_deleted_file("sunset.jpg", b"\xff\xd8\xff" + b"s" * 500,
                             parent_index=folder)
    builder.add_deleted_file("notes.txt", b"n" * 200, parent_index=folder)
    return builder


def test_fragmented_mft_is_walked():
    print("ntfs: fragmented $MFT is walked end to end")
    failures: list[str] = []
    found, _image = _scan(_fragmented_builder())
    names = sorted(c.name for c in found)
    for expected in ("notes.txt", "sunset.jpg"):
        ok = expected in names
        print(f"  {'ok  ' if ok else 'FAIL'} {expected}")
        if not ok:
            failures.append(expected)
    ok = len(found) == 2
    print(f"  {'ok  ' if ok else 'FAIL'} only the 2 deleted files, got {len(found)}")
    if not ok:
        failures.append("count")
    return failures


def test_want_folder_filters_before_reading_data():
    print("ntfs: want_folder narrows the walk")
    failures: list[str] = []
    builder = fsimages.NtfsBuilder()
    keep = builder.add_dir("Keep")
    other = builder.add_dir("Other")
    builder.add_deleted_file("wanted.txt", b"w" * 100, parent_index=keep)
    builder.add_deleted_file("unwanted.txt", b"u" * 100, parent_index=other)
    image = builder.build()
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(image)
        path = fh.name
    try:
        from tizorecover.engine.blockdev import FileBlockReader

        reader = FileBlockReader(path, "ntfs-test")
        try:
            src = ByteSourceView(reader)
            found = list(ntfs.recover_ntfs(src, "ntfs-test", want_folder="C:\\Keep"))
        finally:
            reader.close()
    finally:
        os.unlink(path)
    names = sorted(c.name for c in found)
    ok = names == ["wanted.txt"]
    print(f"  {'ok  ' if ok else 'FAIL'} only the wanted folder, got {names}")
    if not ok:
        failures.append("want_folder")
    return failures


def test_batched_walk_matches_single_reads():
    print("ntfs: batched reads equal single-record reads")
    failures: list[str] = []
    builder = _fragmented_builder()
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(builder.build())
        path = fh.name
    try:
        from tizorecover.engine.blockdev import FileBlockReader

        reader = FileBlockReader(path, "ntfs-test")
        try:
            src = ByteSourceView(reader)
            boot = ntfs.parse_boot_sector(src)
            mft = ntfs.MftMap.locate(src, boot, boot.mft_lcn)
            total = len(mft)

            def shape(entry):
                if entry is None:
                    return None
                return (entry.index, entry.in_use, entry.is_dir, entry.base_index,
                        entry.sequence, len(entry.attributes))

            one = [shape(e) for e in
                   ntfs.iter_mft_entries(src, boot, boot.mft_lcn, total, mft, batch=1)]
            for size in (2, 7, 128, 4096):
                many = [shape(e) for e in
                        ntfs.iter_mft_entries(src, boot, boot.mft_lcn, total, mft,
                                              batch=size)]
                ok = many == one
                print(f"  {'ok  ' if ok else 'FAIL'} batch={size}")
                if not ok:
                    failures.append(f"batch={size}")
        finally:
            reader.close()
    finally:
        os.unlink(path)

    straddles = []
    for index in range(len(mft)):
        if mft.contiguous_span(index, 64) is None:
            continue
        base = mft.offset_of(index)
        for step in range(64):
            if mft.offset_of(index + step) != base + step * mft.boot.mft_record_size:
                straddles.append(index)
                break
    ok = not straddles
    print(f"  {'ok  ' if ok else 'FAIL'} no batch spans an extent boundary ({straddles[:3]})")
    if not ok:
        failures.append("straddle")
    return failures


def test_deleted_parent_folder_still_resolves_paths():
    print("ntfs: files under a deleted folder keep their full path")
    failures: list[str] = []
    builder = fsimages.NtfsBuilder()
    live = builder.add_dir("Videos")
    gone = builder.add_dir("Tizo", parent_index=live)
    builder.add_deleted_file("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"v" * 300,
                             parent_index=gone)
    builder.add_deleted_file("song.mkv", b"\x1a\x45\xdf\xa3" + b"w" * 200,
                             parent_index=gone)
    builder.records[gone] = fsimages.mft_record(
        gone,
        [fsimages.attr_resident(fsimages.N.ATTR_STANDARD_INFORMATION, fsimages.std_info()),
         fsimages.attr_resident(fsimages.N.ATTR_FILE_NAME,
                                fsimages.file_name_attr("Tizo", live, 0, namespace=1)),
         fsimages.attr_nonresident(fsimages.N.ATTR_DATA, b"", 0, 0)],
        in_use=False, is_dir=True)
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(builder.build())
        path = fh.name
    try:
        from tizorecover.engine.blockdev import FileBlockReader

        reader = FileBlockReader(path, "ntfs-test")
        try:
            src = ByteSourceView(reader)
            found = list(ntfs.recover_ntfs(src, "ntfs-test",
                                           want_folder="C:\\Videos\\Tizo"))
        finally:
            reader.close()
    finally:
        os.unlink(path)
    paths = sorted(c.original_path for c in found)
    ok = paths == ["Videos/Tizo/clip.mp4", "Videos/Tizo/song.mkv"]
    print(f"  {'ok  ' if ok else 'FAIL'} paths resolve through the deleted folder: {paths}")
    if not ok:
        failures.append("deleted-parent")
    return failures


def _stub_record_builder():
    """A volume whose $UsnJrnl is a stub plus an $ATTRIBUTE_LIST.

    A real $UsnJrnl keeps only a sliver in its MFT record and lists where the
    rest lives, because its $J runlist cannot fit in 1 KiB. Without following
    the list the journal looks absent when it is right there.
    """
    builder = fsimages.NtfsBuilder(total_clusters=16384, mft_fragments=2,
                                   mft_fragment_lcns=(6000,))
    builder._write_clusters(300, b"USN-PAYLOAD-A" * 8)
    journal = fsimages.attr_nonresident(fsimages.N.ATTR_DATA, [(300, 1)], 4096,
                                        fsimages.CLUSTER, name="$J")
    holder = bytearray(fsimages.mft_record(
        21, [fsimages.attr_resident(fsimages.N.ATTR_STANDARD_INFORMATION,
                                    fsimages.std_info())], in_use=True))
    holder[0x38:0x38 + len(journal)] = journal
    builder.records[21] = bytes(holder)
    builder.records[20] = fsimages.mft_record(
        20, [fsimages.attr_resident(fsimages.N.ATTR_STANDARD_INFORMATION,
                                    fsimages.std_info()),
             fsimages.attr_resident(
                 fsimages.N.ATTR_FILE_NAME,
                 fsimages.file_name_attr("$UsnJrnl", 5, 0, namespace=1)),
             fsimages.attr_resident(0x20, fsimages.attribute_list(
                 [(fsimages.N.ATTR_DATA, 21, 0, 0, "$J")]))],
        in_use=True)
    return builder


def test_attribute_list_is_followed():
    print("ntfs: $ATTRIBUTE_LIST is followed to the real $J stream")
    failures: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as fh:
        fh.write(_stub_record_builder().build())
        path = fh.name
    try:
        from tizorecover.engine.blockdev import FileBlockReader

        reader = FileBlockReader(path, "ntfs-test")
        try:
            src = ByteSourceView(reader)
            boot = ntfs.parse_boot_sector(src)
            mft = ntfs.MftMap.locate(src, boot, boot.mft_lcn)
            raw = src.at(mft.offset_of(20), boot.mft_record_size)
            found = ntfs.follow_attribute_list(src, boot, boot.mft_lcn, 20, raw, mft)
        finally:
            reader.close()
    finally:
        os.unlink(path)

    names = sorted(a.name for a in found)
    ok = names == ["$J"]
    print(f"  {'ok  ' if ok else 'FAIL'} named attribute recovered: {names}")
    if not ok:
        failures.append("name")
    ok = bool(found) and found[0].runs == [(0, 300, 1)]
    print(f"  {'ok  ' if ok else 'FAIL'} runlist intact: "
          f"{found[0].runs if found else None}")
    if not ok:
        failures.append("runs")
    return failures


def test_attribute_name_length_is_bytes():
    print("ntfs: a named attribute's name is not over-read")
    failures: list[str] = []
    attr = fsimages.attr_nonresident(fsimages.N.ATTR_DATA, [(300, 1)], 4096,
                                     fsimages.CLUSTER, name="$J")
    parsed = ntfs.parse_attribute_at(attr, 0)
    ok = parsed is not None and parsed.name == "$J"
    print(f"  {'ok  ' if ok else 'FAIL'} name={parsed.name if parsed else None!r}")
    if not ok:
        failures.append("name-bytes")
    return failures


def main() -> int:
    failures: list[str] = []
    for test in (
        test_boot_sector,
        test_named_contiguous_file,
        test_resident_file,
        test_fragmented_file_reports_gaps,
        test_live_files_excluded,
        test_many_files,
        test_fragmented_mft_is_walked,
        test_want_folder_filters_before_reading_data,
        test_batched_walk_matches_single_reads,
        test_deleted_parent_folder_still_resolves_paths,
        test_attribute_list_is_followed,
        test_attribute_name_length_is_bytes,
    ):
        failures.extend(test())
    print()
    if failures:
        print(f"FAILURES ({len(failures)}): {failures}")
        return 1
    print("all ntfs tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
