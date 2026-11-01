#!/bin/bash
# Copy the run's state from the cloud server back to this Mac every few minutes, so the
# progress page and summary.py see it: results.jsonl, sub.icnf and cover.out of every node,
# the conquer log, and the server's process list (read by progress_server.py).
# Usage: nohup bash scripts/cloud/sync_back.sh HOST_IP [SECONDS] &
set -u
cd "$(dirname "$0")/../.."
HOST="ubuntu@$1"
EVERY="${2:-600}"
SSH="ssh -i $HOME/.ssh/kobon-aws.pem -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20"
TOP=results/cubes_k11B_lex_d8

while true; do
  rsync -az -e "$SSH" --include '*/' --include 'results.jsonl' --include 'sub.icnf' \
    --include 'cover.out' --exclude '*' "$HOST:kobon/$TOP/" "$TOP/" \
    && rsync -az -e "$SSH" "$HOST:kobon/$TOP.conquer.log" "$TOP.conquer.log" \
    && $SSH "$HOST" 'ps -axo etime=,args=' > "$TOP.remote_ps.tmp" \
    && mv "$TOP.remote_ps.tmp" "$TOP.remote_ps.txt" \
    && echo "$(date '+%F %T') synced"
  sleep "$EVERY"
done
