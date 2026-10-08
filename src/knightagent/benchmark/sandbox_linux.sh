#!/usr/bin/env bash
# Called by the trusted Windows runner through WSL as root. Candidate code runs
# as nobody after chroot, in fresh mount/network/PID namespaces with rlimits.
set -euo pipefail

worker="$1"
memory_bytes="$2"
cpu_seconds="$3"
wall_seconds="$4"
root="$(mktemp -d /tmp/knightagent-bench.XXXXXXXX)"
case "$root" in /tmp/knightagent-bench.[A-Za-z0-9]*) ;; *) exit 125 ;; esac
cleanup() { rm -rf -- "$root"; }
trap cleanup EXIT

mkdir -p "$root/usr" "$root/work"
chmod 755 "$root"
chmod 1777 "$root/work"
cp -- "$worker" "$root/work/worker.py"
chmod 644 "$root/work/worker.py"
ln -s usr/bin "$root/bin"
ln -s usr/lib "$root/lib"
ln -s usr/lib64 "$root/lib64"

timeout --signal=KILL "${wall_seconds}s" \
  unshare --mount --net --pid --fork -- bash -ceu '
    mount --bind /usr "$1/usr"
    mount -o remount,bind,ro "$1/usr"
    cd "$1/work"
    env -i PATH=/usr/sbin:/usr/bin:/bin HOME=/work TMPDIR=/work PYTHONUTF8=1 \
      prlimit --as="$2" --cpu="$3" --fsize=1048576 --nofile=32 --nproc=16 --core=0 -- \
      chroot --userspec=65534:65534 "$1" /usr/bin/python3 -I -S /work/worker.py
  ' bash "$root" "$memory_bytes" "$cpu_seconds"
