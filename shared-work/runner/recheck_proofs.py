#!/usr/bin/env python3
"""Fetch the proofs a participant linked and check them again. Holds no Papex credential.

  python3 shared-work/runner/recheck_proofs.py JOB.json OUT.json

JOB.json:  {"manifest": "pilot-v1.manifest.ndjson",
            "units": [{"key": "c201.c63:17", "url": "https://…", "sha256": "0x…", "bytes": 123}]}
           A unit may name "stored": "proofs.tar.xz" in place of "url": a file in JOB.json's own
           directory, which the runner fetched from Papex (the kit sent it there with the batch's
           key). It is read exactly as a download is, and is as untrusted.
OUT.json:  {"c201.c63:17": {"result": "VERIFIED" | "FAILED" | "UNREACHABLE", "checkedWith": "…",
            "detail": "…"}}

For every unit: the link is fetched, the proof is found in what came back (the proof file itself,
the same file compressed with xz or gzip, or the kit's .tar.xz with several proofs, or a .zip), its
size and SHA-256 are compared with what the result file declared, the unit's formula is written
again from this repository and compared with the manifest's input SHA-256, and the patched
lrat-check reads formula and proof. With the environment variable CAKE_LPR naming a cake_lpr
binary, the proof must pass that checker too.

UNREACHABLE means the link gave nothing usable (no answer, too large, or no file of the declared
size and hash in it). FAILED means the declared proof was there and a checker did not verify it.

Every link is untrusted input. Only https on port 443 is followed, at most 5 redirects, each to a
public address; downloads and unpacking are capped in size and time; the checker runs with a time
limit. Run this in a throwaway container or VM with nothing else in it (Dockerfile next to this
file): the limits here are a second line, not the isolation.
"""

import gzip
import hashlib
import ipaddress
import json
import lzma
import os
import resource
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tree  # noqa: E402
from run_cubes import lrat_verdict  # noqa: E402

MAX_DOWNLOAD = int(os.environ.get("RECHECK_MAX_DOWNLOAD", 2 * 1024 ** 3))
MAX_UNPACKED = int(os.environ.get("RECHECK_MAX_UNPACKED", 8 * 1024 ** 3))
FETCH_SECONDS = int(os.environ.get("RECHECK_FETCH_SECONDS", 1800))
CHECK_SECONDS = int(os.environ.get("RECHECK_CHECK_SECONDS", 3600))
MAX_REDIRECTS = 5
MAX_MEMBERS = 2000
CHECKER = os.environ.get("LRAT_CHECK") or os.path.join(tree.ROOT, "checker", "lrat-check")
CAKE_LPR = os.environ.get("CAKE_LPR")


class Unreachable(Exception):
    pass


def public_address(host):
    """One address of the host, after making sure every address it resolves to is public."""
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError as e:
        raise Unreachable(f"the host of the link does not resolve: {e}")
    if not addresses or any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise Unreachable("the link points to an address that is not public")
    v4 = [a for a in addresses if ":" not in a]
    return v4[0] if v4 else addresses[0]


def fetch(url, dest):
    """Download url to dest, following redirects by hand so that every hop is checked."""
    headers = dest + ".headers"
    for _ in range(MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password \
                or parts.port not in (None, 443):
            raise Unreachable("only plain https links on port 443 are followed")
        address = public_address(parts.hostname)
        pinned = f"{parts.hostname}:443:{'[' + address + ']' if ':' in address else address}"
        cmd = ["curl", "--silent", "--show-error", "--proto", "=https", "--max-redirs", "0",
               "--resolve", pinned, "--connect-timeout", "30", "--max-time", str(FETCH_SECONDS),
               "--max-filesize", str(MAX_DOWNLOAD), "--user-agent", "papex-shared-work-runner",
               "--dump-header", headers, "--output", dest, url]

        def limit():
            resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_DOWNLOAD, MAX_DOWNLOAD))

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=FETCH_SECONDS + 60,
                               preexec_fn=limit)
        except subprocess.TimeoutExpired:
            raise Unreachable("the download took too long")
        status, location = 0, None
        if os.path.exists(headers):
            for line in open(headers, errors="replace"):
                if line.startswith("HTTP/"):
                    fields = line.split()
                    status, location = (int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else 0), None
                elif line.lower().startswith("location:"):
                    location = line.split(":", 1)[1].strip()
        if status in (301, 302, 303, 307, 308) and location:
            url = urllib.parse.urljoin(url, location)
            continue
        if r.returncode != 0 or status != 200:
            raise Unreachable(f"the link answered {status or 'nothing'} ({r.stderr.strip()[:120]})")
        return
    raise Unreachable("too many redirects")


def unpack_outer(path, tmp):
    """If the download is one xz or gzip stream, write what is inside to a new file (size capped)."""
    with open(path, "rb") as fh:
        magic = fh.read(6)
    opener = lzma.open if magic.startswith(b"\xfd7zXZ\x00") else gzip.open if magic[:2] == b"\x1f\x8b" else None
    if opener is None:
        return path
    inner = os.path.join(tmp, "inner")
    written = 0
    try:
        with opener(path, "rb") as src, open(inner, "wb") as dst:
            for block in iter(lambda: src.read(1 << 20), b""):
                written += len(block)
                if written > MAX_UNPACKED:
                    raise Unreachable("the linked file unpacks to more than the size limit")
                dst.write(block)
    except (OSError, EOFError, lzma.LZMAError) as e:
        raise Unreachable(f"the linked file could not be unpacked: {e}")
    return inner


def copy_if_match(src, size, wanted, dest_dir):
    """Stream src (size bytes) to a file and keep it if its hash is one a unit declared."""
    by_hash = {w["sha256"]: w for w in wanted if w["bytes"] == size and "file" not in w}
    if not by_hash:
        return
    h = hashlib.sha256()
    tmp_path = os.path.join(dest_dir, "candidate")
    left = size
    with open(tmp_path, "wb") as out:
        while left > 0:
            block = src.read(min(1 << 20, left))
            if not block:
                break
            h.update(block)
            out.write(block)
            left -= len(block)
    unit = by_hash.get("0x" + h.hexdigest())
    if left == 0 and unit:
        unit["file"] = os.path.join(dest_dir, "proof-" + unit["sha256"][2:18])
        os.replace(tmp_path, unit["file"])
    else:
        os.unlink(tmp_path)


def find_proofs(path, wanted, tmp):
    """Mark every wanted unit whose proof (declared bytes and sha256) is in the downloaded file."""
    inner = unpack_outer(path, tmp)
    try:
        if tarfile.is_tarfile(inner):
            with tarfile.open(inner, "r:") as tar:
                for n, member in enumerate(tar):
                    if n >= MAX_MEMBERS:
                        break
                    if member.isreg():
                        copy_if_match(tar.extractfile(member), member.size, wanted, tmp)
        elif zipfile.is_zipfile(inner):
            with zipfile.ZipFile(inner) as z:
                for info in z.infolist()[:MAX_MEMBERS]:
                    if not info.is_dir():
                        with z.open(info) as src:
                            copy_if_match(src, info.file_size, wanted, tmp)
        else:
            with open(inner, "rb") as src:
                copy_if_match(src, os.path.getsize(inner), wanted, tmp)
    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError, lzma.LZMAError) as e:
        raise Unreachable(f"the linked file could not be read: {e}")


def check(key, proof, manifest, top, tmp):
    formula = tree.leaf_formula(top, key)
    if "0x" + hashlib.sha256(formula).hexdigest() != manifest[key]["inputSha256"]:
        raise SystemExit(f"{key}: the formula written here is not the manifest's; this copy of the "
                         "repository is wrong, nothing was decided")
    cnf = os.path.join(tmp, "unit.cnf")
    with open(cnf, "wb") as fh:
        fh.write(formula)
    used = []
    for name, binary in (("patched lrat-check", CHECKER), ("cake_lpr", CAKE_LPR)):
        if not binary:
            continue
        used.append(name)
        try:
            r = subprocess.run([binary, cnf, proof], capture_output=True, text=True, timeout=CHECK_SECONDS)
        except subprocess.TimeoutExpired:
            return "FAILED", ", ".join(used), f"{name} did not finish in {CHECK_SECONDS} s"
        # the rules of scripts/run_cubes.py and scripts/check_cover.py
        ok = lrat_verdict(r.returncode, r.stdout + r.stderr) == "VERIFIED" if name != "cake_lpr" \
            else r.returncode == 0 and r.stdout.strip() == "s VERIFIED UNSAT" and not r.stderr
        if not ok:
            return "FAILED", ", ".join(used), f"{name} did not verify the proof"
    return "VERIFIED", ", ".join(used), None


def main():
    job = json.load(open(sys.argv[1]))
    manifest = {u["key"]: u for u in map(json.loads, open(os.path.join(os.path.dirname(HERE), job["manifest"])))}
    top = tree.ensure_top_cnf()
    out = {}
    by_url = {}
    for unit in job["units"]:
        if unit["key"] not in manifest:
            raise SystemExit(f"{unit['key']} is not a unit of {job['manifest']}")
        source = ("stored", unit["stored"]) if unit.get("stored") else ("url", unit["url"])
        by_url.setdefault(source, []).append(dict(unit))
    for n, ((kind, where), wanted) in enumerate(by_url.items()):
        tmp = tempfile.mkdtemp(prefix="recheck-")
        try:
            try:
                if kind == "stored":
                    # A bare file name next to the job file, never a path: the runner put it there.
                    download = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), where)
                    if os.path.basename(where) != where or where.startswith(".") or not os.path.isfile(download):
                        raise Unreachable("the stored file is not in the job directory")
                    if os.path.getsize(download) > MAX_DOWNLOAD:
                        raise Unreachable("the stored file is larger than the size limit")
                    find_proofs(download, wanted, tmp)
                    problem = "the stored file has no proof with the declared size and SHA-256"
                else:
                    download = os.path.join(tmp, "download")
                    fetch(where, download)
                    find_proofs(download, wanted, tmp)
                    problem = "the link has no file with the declared size and SHA-256"
            except Unreachable as e:
                problem = str(e)
            for unit in wanted:
                if "file" not in unit:
                    out[unit["key"]] = {"result": "UNREACHABLE", "checkedWith": None, "detail": problem}
                    continue
                result, used, detail = check(unit["key"], unit["file"], manifest, top, tmp)
                out[unit["key"]] = {"result": result, "checkedWith": used, "detail": detail}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"{'stored file' if kind == 'stored' else 'link'} {n + 1} of {len(by_url)}: " + ", ".join(
            f"{u['key']} {out[u['key']]['result']}" for u in wanted), flush=True)
    with open(sys.argv[2], "w") as fh:
        json.dump(out, fh, indent=1)


if __name__ == "__main__":
    main()
