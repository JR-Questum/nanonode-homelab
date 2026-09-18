#!/usr/bin/env bash
# Exercise roles/deploy_airable_proxy/files/airable_tap.py against a local
# origin. No Docker, no network, no target host.
#
#   ./run.sh
#
# The point of these is the relay half: the tap must hand every framing
# back byte-for-byte. If a change breaks that, it breaks the radio's
# whole catalogue, not just the logging.
set -u
cd "$(dirname "$0")"
TAP=../../roles/deploy_airable_proxy/files/airable_tap.py
WORK=$(mktemp -d)
trap 'kill ${TPID:-} ${OPID:-} 2>/dev/null; rm -rf "$WORK"' EXIT

command -v openssl >/dev/null || { echo "openssl required"; exit 1; }
[ -f cert.pem ] || openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 30 -nodes -subj "/CN=airable.wifiradiofrontier.com" >/dev/null 2>&1

python3 origin.py 18080 >"$WORK/origin.log" 2>&1 & OPID=$!
AIRABLE_TAP_UPSTREAM=127.0.0.1 \
AIRABLE_TAP_PORTS=18081:http:18080,18091:http:19999 \
AIRABLE_TAP_LOG=$PWD/tap.jsonl AIRABLE_TAP_MAX_BODY=1024 \
AIRABLE_TAP_STATUS_PORT=18099 python3 -u $TAP >"$WORK/tap.out" 2>&1 & TPID=$!
for _ in $(seq 1 40); do nc -z 127.0.0.1 18081 2>/dev/null && nc -z 127.0.0.1 18080 2>/dev/null && break; done

rc=0
echo "=== relay fidelity ==="  ; python3 drive.py 18081      || rc=1
sleep 0.4
echo; echo "=== log correctness ==="; python3 verify_log.py  || rc=1
echo; echo "=== upstream down ===" ; python3 fail_test.py    || rc=1
kill $TPID $OPID 2>/dev/null; wait 2>/dev/null

AIRABLE_TAP_UPSTREAM=127.0.0.1 AIRABLE_TAP_PORTS=18444:tls:18443 \
AIRABLE_TAP_LOG=$PWD/tls.jsonl AIRABLE_TAP_STATUS_PORT=0 \
python3 -u $TAP >"$WORK/tls.out" 2>&1 & TPID=$!
for _ in $(seq 1 40); do nc -z 127.0.0.1 18444 2>/dev/null && break; done
sleep 0.2
echo; echo "=== tls passthrough ==="; python3 tls_test.py || rc=1
kill $TPID 2>/dev/null; wait 2>/dev/null

echo; echo "=== control characters ==="; python3 control_char_test.py || rc=1

echo; echo "=== certificate probe ==="; python3 probe_test.py || rc=1

echo; echo "=== album artwork fetcher ==="; python3 artwork_test.py || rc=1

echo; echo "=== catalogue rewrite ==="; python3 rewrite_test.py || rc=1

echo; echo "=== artwork serving ==="; python3 asset_test.py || rc=1

rm -f tap.jsonl tls.jsonl probeA.jsonl probeB.jsonl probeC.jsonl probeD.jsonl rw.jsonl rewrites.json as.jsonl assets.json logo.png cover.png cover.png.new last.txt
echo; [ $rc -eq 0 ] && echo "ALL PASS" || echo "FAILURES"
exit $rc
