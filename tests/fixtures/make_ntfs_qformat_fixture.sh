set -e
SRC="$1"; OUT="$2"
IMG=/tmp/ntfs-qformat.img
rm -f $IMG; truncate -s 48M $IMG
mkntfs -q -F -Q -c 4096 -L before $IMG >/dev/null
M=/mnt/tizoqf; mkdir -p $M
ntfs-3g $IMG $M
mkdir -p $M/DCIM/Camera $M/Documents/Work $M/Videos
cp "$SRC"/DCIM/Camera/* $M/DCIM/Camera/
cp "$SRC"/Documents/Work/* $M/Documents/Work/
# Write the video 64 KiB at a time, alternating with a spacer file, so it ends up in pieces.
mkdir -p $M/tmp
V="$SRC"/Videos/holiday.mov
N=$(( ($(stat -c %s "$V") + 65535) / 65536 ))
for k in $(seq 0 $((N - 1))); do
  dd if="$V" of=$M/Videos/holiday.mov bs=65536 skip=$k seek=$k count=1 conv=notrunc status=none
  sync
  yes s | head -c 65536 >> $M/tmp/spacer
  sync
done
rm -rf $M/tmp
sync; sleep 2
umount $M
# The accident: a quick format (new, empty file system; nothing else written).
mkntfs -q -F -Q -c 4096 -L after $IMG >/dev/null
# Then a little use, as people do before they notice.
ntfs-3g $IMG $M
printf 'new stick\n' > $M/readme.txt
sync; sleep 1
umount $M
gzip -9 -c $IMG > "$OUT"
ls -la "$OUT"
