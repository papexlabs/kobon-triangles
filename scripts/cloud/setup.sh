#!/bin/bash
# Prepare a fresh Ubuntu 24.04 server (arm64 or x86_64) for conquer.py.
# Run on the server from ~/kobon after copying tools/drat-trim, tools/CnC/march_cu (sources),
# scripts/, src/ and build/ there:  bash scripts/cloud/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update
sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y build-essential git rsync python3 > /dev/null

# lrat-check, as in tools/drat-trim/Makefile
(cd tools/drat-trim && gcc lrat-check.c -std=c99 -DLONGTYPE -O2 -o lrat-check)

# march_cu needs -fcommon with GCC 10 and later (shared globals across files)
(cd tools/CnC/march_cu && rm -f ./*.o && make -s CFLAGS="-O3 -fno-strict-aliasing -DNDEBUG -fcommon")

# CaDiCaL 3.0.1, the version used on the Mac
if ! command -v cadical > /dev/null || [ "$(cadical --version)" != "3.0.1" ]; then
  rm -rf /tmp/cadical
  git clone -q https://github.com/arminbiere/cadical.git /tmp/cadical
  (cd /tmp/cadical && git checkout -q rel-3.0.1 && ./configure > /dev/null 2>&1 && make -s -j"$(nproc)" > /dev/null 2>&1)
  sudo install -m 755 /tmp/cadical/build/cadical /usr/local/bin/cadical
fi

cadical --version
ls -la tools/drat-trim/lrat-check tools/CnC/march_cu/march_cu | awk '{print $5, $NF}'
