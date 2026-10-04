set -e
SRC="$1"; OUT="$2"
IMG=/tmp/ext4-fixture.img
rm -f $IMG; truncate -s 16M $IMG
mkfs.ext4 -q -b 4096 -J size=4 -L fixture -E lazy_itable_init=0,lazy_journal_init=0 -U 00000000-0000-4000-8000-000000000001 $IMG
M=/mnt/tizofix; mkdir -p $M; mount -o loop $IMG $M
mkdir -p $M/home/user/Photos $M/home/user/Old $M/etc
cp "$SRC/photo1.png" "$SRC/photo2.png" $M/home/user/Photos/
cp "$SRC/report.pdf" "$SRC/notes.txt" $M/home/user/
cp "$SRC/plan.txt" "$SRC/data.bin" $M/home/user/Old/
echo "fixture" > $M/etc/hostname
for i in 1 2 3 4 5 6; do head -c 20000 "$SRC/frag_part$i" >> $M/home/user/frag.bin; head -c 20000 "$SRC/filler_part$i" >> $M/home/user/filler.bin; sync; done
sync; sleep 6
rm $M/home/user/Photos/photo1.png $M/home/user/report.pdf $M/home/user/frag.bin
rm -r $M/home/user/Old
sync; sleep 6; umount $M
gzip -9 -c $IMG > "$OUT"
ls -la "$OUT"
