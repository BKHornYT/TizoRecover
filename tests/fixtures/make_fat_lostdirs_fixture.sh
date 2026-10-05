set -e
SRC="$1"; OUT="$2"
IMG=/tmp/fat-lostdirs.img
rm -f $IMG; truncate -s 64M $IMG
mkfs.vfat -F 32 -s 8 -n BEFORE $IMG >/dev/null
export MTOOLS_SKIP_CHECK=1
mmd -i $IMG ::DCIM ::DCIM/100MEDIA ::Documents ::Documents/Work ::Music
mcopy -i $IMG "$SRC"/DCIM/100MEDIA/* ::DCIM/100MEDIA/
mcopy -i $IMG "$SRC"/Documents/Work/* ::Documents/Work/
mcopy -i $IMG "$SRC"/Music/* ::Music/
# The accident: a quick format (new FAT and root folder; the old folders stay in the data area).
mkfs.vfat -F 32 -s 8 -n AFTER $IMG >/dev/null
printf 'new stick\n' > /tmp/readme.txt
mcopy -i $IMG /tmp/readme.txt ::readme.txt
gzip -9 -c $IMG > "$OUT"
ls -la "$OUT"
