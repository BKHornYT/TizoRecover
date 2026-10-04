set -e
SRC="$1"; OUT="$2"
IMG=/tmp/ntfs-fixture.img
rm -f $IMG; truncate -s 32M $IMG
mkntfs -q -F -Q -c 4096 -L fixture $IMG >/dev/null
M=/mnt/tizontfs; mkdir -p $M
ntfs-3g $IMG $M
mkdir -p $M/DCIM/Photos $M/Notes
cp "$SRC"/IMG_*.png $M/DCIM/Photos/
sync; sleep 2
# delete 5 photos from the middle of the folder and the 10 newest (end of the index, newest first),
# then make tiny (MFT-resident) files so their MFT records get reused:
for i in $(seq 1010 1014) $(seq 1040 -1 1031); do rm $M/DCIM/Photos/IMG_$i.png; done
sync; sleep 2
for i in $(seq 1 30); do printf 'note %s\n' $i > $M/Notes/note_$i.txt; done
sync; sleep 2
umount $M
gzip -9 -c $IMG > "$OUT"
ls -la "$OUT"
