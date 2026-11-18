#!/usr/bin/env python3
"""Run a batch of the Kobon shared-work list on your own computer.

  python3 shared-work/run_batch.py --key KIT_KEY [--api URL] [--workers N] [--agent-host NAME]
  python3 shared-work/run_batch.py BATCH_FILE [--workers N] [--agent-host NAME]
  python3 shared-work/run_batch.py --check

Your batch page on papex.org shows the first command with a key for your batch, to copy. With the
key the kit fetches the batch from Papex, tells Papex how many units are done while it runs, and
sends the result file at the end. Nothing else leaves this computer, and the key is never written
to a file or printed. --api names another Papex server (default https://api.papex.org).

BATCH_FILE is the batch file you can download from the batch page instead. Then the kit sends
nothing anywhere, and you upload the result file on the batch page yourself.

For every unit of the batch the kit writes the unit's formula, solves it with CaDiCaL, which writes
an LRAT proof, and checks that proof with the patched lrat-check of this repository (checker/). It
then writes two files in shared-work/work/BATCH/:

  BATCH.result.json     the result; with BATCH_FILE a copy is put next to it, to upload
  BATCH.proofs.tar.xz   the proofs of the units the batch marks; keep it until the batch is decided

A stopped run continues where it stopped when you give the same command again. --check only tests
that the tools on this computer work.

Needs Python 3.9 or later, a C compiler (cc) and CaDiCaL 1.9.0 or later as `cadical` on the PATH
(or named by the environment variable CADICAL). See shared-work/README.md.
"""

import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tree  # noqa: E402
from run_cubes import lrat_verdict  # noqa: E402  (tree put scripts/ on the path)

BATCH_SCHEMA = "papex-shared-work-batch/v1"
RESULT_SCHEMA = "papex-shared-work-result/v1"
RESULT_MAX_BYTES = 262144
KIT_VERSION = "2"
CHECKER_SRC = os.path.join(tree.ROOT, "checker", "lrat-check.c")
CHECKER_VERSION = "drat-trim 2e3b2dc + empty-clause patch"
WORK = os.path.join(HERE, "work")
AGENT_HOST_RE = re.compile(r"^[\w ._+()/:-]{1,80}$")
DEFAULT_API = "https://api.papex.org"
KEY_RE = re.compile(r"^swk_[A-Za-z0-9_-]{43}$")
KEY_HASHES = "kit-keys.sha256"  # in a batch's work folder: the SHA-256 of each key used, never a key
PROGRESS_GAP = 2.0      # seconds between two progress reports at least
PROGRESS_TIMEOUT = 5.0  # seconds a progress report may take

# Pigeonhole: 4 pigeons do not fit in 3 holes. Small, unsatisfiable, and it needs real proof steps.
SELFTEST_UNSAT = "p cnf 12 22\n" + "".join(
    f"{3 * i + 1} {3 * i + 2} {3 * i + 3} 0\n" for i in range(4)) + "".join(
    f"-{3 * i + j + 1} -{3 * k + j + 1} 0\n" for j in range(3) for i in range(4) for k in range(i + 1, 4))
# drat-trim issue #42: the unpatched checker prints VERIFIED for this proof of a satisfiable formula.
SELFTEST_SAT = "p cnf 2 2\n1 2 0\n-1 2 0\n"
SELFTEST_BAD_PROOF = "3 0 0\n"

running = set()
running_lock = threading.Lock()
say_lock = threading.Lock()


def stop(message):
    raise SystemExit(message)


def say(line):
    """Print one line; the progress thread prints too, so a line is never cut by another."""
    with say_lock:
        print(line, flush=True)


def call(cmd):
    """Run a tool to its end; Ctrl-C in the main thread can end it early."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    with running_lock:
        running.add(p)
    try:
        out, _ = p.communicate()
    finally:
        with running_lock:
            running.discard(p)
    return p.returncode, out


def find_tools():
    cadical = os.environ.get("CADICAL") or shutil.which("cadical")
    if not cadical:
        stop("CaDiCaL was not found. Install it (macOS: brew install cadical; Linux: build it from\n"
             "https://github.com/arminbiere/cadical and put build/cadical on the PATH), then run this again.")
    version = subprocess.run([cadical, "--version"], capture_output=True, text=True).stdout.strip()
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if not m or tuple(int(x) for x in m.groups()) < (1, 9, 0):
        stop(f"CaDiCaL 1.9.0 or later is needed for LRAT proofs; this one says '{version}'.")
    checker = os.environ.get("LRAT_CHECK")
    if not checker:
        checker = os.path.join(tree.ROOT, "checker", "lrat-check")
        if not os.path.exists(checker) or os.path.getmtime(checker) < os.path.getmtime(CHECKER_SRC):
            cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
            if not cc:
                stop("A C compiler was not found (cc). Install one (macOS: xcode-select --install; "
                     "Debian or Ubuntu: sudo apt install build-essential), then run this again.")
            r = subprocess.run([cc, "-std=c99", "-DLONGTYPE", "-O2", "-o", checker, CHECKER_SRC],
                               capture_output=True, text=True)
            if r.returncode != 0:
                stop("Building checker/lrat-check failed:\n" + r.stderr)
    return {"cadical": cadical, "cadical_version": version, "checker": checker}


def self_test(tools):
    """passed/failed for the solver and for the checker, on two tiny formulas."""
    tmp = os.path.join(WORK, "selftest")
    os.makedirs(tmp, exist_ok=True)
    cnf, prf = os.path.join(tmp, "php43.cnf"), os.path.join(tmp, "php43.lrat")
    sat, bad = os.path.join(tmp, "sat.cnf"), os.path.join(tmp, "sat.lrat")
    for path, text in ((cnf, SELFTEST_UNSAT), (sat, SELFTEST_SAT), (bad, SELFTEST_BAD_PROOF)):
        with open(path, "w") as fh:
            fh.write(text)
    if os.path.exists(prf):
        os.unlink(prf)
    code, _ = call([tools["cadical"], "-q", "--lrat=true", "--binary=false", cnf, prf])
    solved = code == 20 and os.path.exists(prf) and os.path.getsize(prf) > 0
    good = solved and lrat_verdict(*call([tools["checker"], cnf, prf])) == "VERIFIED"
    rejects = lrat_verdict(*call([tools["checker"], sat, bad])) == "FAILED"
    shutil.rmtree(tmp, ignore_errors=True)
    return {"cadical": "passed" if solved and good else "failed",
            "lrat-check": "passed" if good and rejects else "failed"}


def cpu_name():
    try:
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True).stdout.strip()
        for line in open("/proc/cpuinfo"):
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def missing_batch_file(path):
    """What to say when the named batch file is not there: most often the example name was typed."""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        found = sorted((n for n in os.listdir(folder) if re.match(r"^b-[0-9a-f]{6,10}\.json$", n)),
                       key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True)
    except OSError:
        found = []
    lines = [f"There is no file {path}.",
             "A batch file is named after its batch, for example b-948ffd.json. Your batch page on "
             "papex.org shows the command with your file's name."]
    if found:
        lines.append(f"Batch files in {folder}: {', '.join(found[:5])}")
        lines.append(f"Run:  python3 shared-work/run_batch.py {os.path.join(os.path.dirname(path), found[0])}")
    return "\n".join(lines)


def load_batch(path):
    if not os.path.exists(path):
        stop(missing_batch_file(path))
    try:
        batch = json.load(open(path))
    except (OSError, ValueError) as e:
        stop(f"{path} could not be read as a batch file: {e}")
    if not isinstance(batch, dict) or batch.get("schema") != BATCH_SCHEMA \
            or batch.get("resultSchema") != RESULT_SCHEMA:
        stop(f"{path} is not a Papex batch file ({BATCH_SCHEMA}). Download it from your batch page.")
    if not re.match(r"^b-[0-9a-f]{6,10}$", str(batch.get("batch"))) or not batch.get("units"):
        stop(f"{path} names no batch or has no units.")
    return batch


def load_manifest(list_sha256):
    """The list's manifest in this copy of the repository: unit key -> its line."""
    for name in sorted(os.listdir(HERE)):
        path = os.path.join(HERE, name)
        if name.endswith(".manifest.ndjson") and "0x" + tree.sha256_file(path) == list_sha256:
            return {u["key"]: u for u in map(json.loads, open(path))}
    stop("This batch belongs to a list that this copy of the repository does not have.\n"
         "Update it (git pull) and run this again.")


def run_unit(unit, top, manifest, work, tools, nice):
    key, keep = unit["key"], bool(unit.get("keepProof"))
    safe = key.replace(":", "_")
    cnf = os.path.join(work, "tmp", safe + ".cnf")
    prf = os.path.join(work, "tmp", safe + ".lrat")
    formula = tree.leaf_formula(top, key)
    rec = {"key": key, "inputSha256": "0x" + hashlib.sha256(formula).hexdigest()}
    if rec["inputSha256"] != manifest[key]["inputSha256"]:
        rec["outcome"] = "INPUT_MISMATCH"
        return rec
    with open(cnf, "wb") as fh:
        fh.write(formula)
    if os.path.exists(prf):
        os.unlink(prf)
    t0 = time.time()
    code, out = call(nice + [tools["cadical"], "-q", "--lrat=true", "--binary=false", cnf, prf])
    rec["seconds"] = round(time.time() - t0, 1)
    if code == 20 and os.path.exists(prf) and os.path.getsize(prf) > 0:
        rec.update(outcome="UNSAT", proofSha256="0x" + tree.sha256_file(prf),
                   proofBytes=os.path.getsize(prf))
        rec["check"] = lrat_verdict(*call([tools["checker"], cnf, prf]))
        if keep or rec["check"] != "VERIFIED":
            os.replace(prf, os.path.join(work, "proofs", safe + ".lrat"))
    elif code == 10:
        model = os.path.join(work, "models", safe + ".model")
        with open(model, "w") as fh:
            fh.write(out)
        os.replace(cnf, os.path.join(work, "models", safe + ".cnf"))
        rec.update(outcome="SAT", proofSha256="0x" + tree.sha256_file(model),
                   proofBytes=os.path.getsize(model))
    else:
        rec["outcome"] = "UNKNOWN"
    for path in (cnf, prf):
        if os.path.exists(path):
            os.unlink(path)
    return rec


def result_file(batch, records, tools, tests, agent_host):
    units = []
    for unit in batch["units"]:
        r = records.get(unit["key"])
        if not r:
            continue
        units.append({
            "key": r["key"], "outcome": r["outcome"], "seconds": r["seconds"],
            "proof": {"sha256": r["proofSha256"], "bytes": r["proofBytes"]},
            "checks": [{"tool": "lrat-check", "result": r["check"]}] if "check" in r else [],
            "extra": {"inputSha256": r["inputSha256"]},
        })
    env = {
        "os": platform.platform()[:120],
        "cpu": cpu_name()[:120],
        "tools": [
            {"name": "cadical", "version": tools["cadical_version"][:60], "selfTest": tests["cadical"]},
            {"name": "lrat-check", "version": CHECKER_VERSION,
             "sourceSha256": "0x" + tree.sha256_file(CHECKER_SRC), "selfTest": tests["lrat-check"]},
            {"name": "kobon-shared-work-kit", "version": KIT_VERSION,
             "sourceSha256": "0x" + tree.sha256_file(os.path.abspath(__file__))},
        ],
    }
    if agent_host:
        env["agentHost"] = agent_host
    return {"schema": RESULT_SCHEMA, "problem": batch["problem"], "list": batch["list"],
            "listSha256": batch["listSha256"], "batch": batch["batch"], "env": env, "units": units}


def bundle(work, batch_key, kept, records):
    """One archive with the proofs of the marked units and a list of what is in it."""
    path = os.path.join(work, f"{batch_key}.proofs.tar.xz")
    index = {"batch": batch_key, "proofs": [
        {"unit": k, "file": k.replace(":", "_") + ".lrat", "sha256": records[k]["proofSha256"],
         "bytes": records[k]["proofBytes"]} for k in kept]}
    index_path = os.path.join(work, "proofs", "proofs.json")
    with open(index_path, "w") as fh:
        json.dump(index, fh, indent=1)
    with tarfile.open(path, "w:xz", preset=3) as tar:
        tar.add(index_path, arcname="proofs.json")
        for entry in index["proofs"]:
            tar.add(os.path.join(work, "proofs", entry["file"]), arcname=entry["file"])
    return path


# With --key: the three kit routes of Papex. Standard library only.

class KitError(Exception):
    """An answer of Papex that is not a success (status), or no answer at all (status None)."""

    def __init__(self, status, text):
        super().__init__(text)
        self.status = status

    def why(self):
        return str(self).rstrip(".")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is taken as an error, so the key never goes to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Kit:
    """The kit routes of Papex for one batch. The key goes only into the Authorization header."""

    def __init__(self, api, key):
        self.api, self.key = api, key
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, route, body=None, timeout=30.0):
        req = urllib.request.Request(self.api + "/api/shared-work/kit" + route, data=body, method=method)
        req.add_unredirected_header("Authorization", "Bearer " + self.key)
        req.add_header("User-Agent", "kobon-shared-work-kit/" + KIT_VERSION)
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=timeout) as answer:
                return answer.read()
        except urllib.error.HTTPError as e:
            try:  # Papex answers an error with {"code": ..., "error": "what happened", ...}
                answer = json.loads(e.read().decode("utf-8", "replace"))
                text = answer.get("error") or answer.get("message")
            except (ValueError, AttributeError, OSError):
                text = None
            raise KitError(e.code, " ".join(str(text).split())[:300] if text else f"HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
            reason = str(getattr(e, "reason", None) or e) or type(e).__name__
            raise KitError(None, f"no answer: {reason}") from None


class Progress:
    """Tells Papex how many units are done, from a thread of its own, so the run never waits for it.

    The first report goes at once, then at most one every PROGRESS_GAP seconds with the newest count,
    and the last when finish() is called (unless the report before it already carried that count).
    A report that fails is dropped: the first failure prints one line, later ones are silent."""

    def __init__(self, kit, done):
        self.kit, self.done = kit, done
        self.sent = self.at = None
        self.final = self.closed = self.failed = self.ok = False
        self.cond = threading.Condition()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def update(self, done):
        with self.cond:
            self.done = done
            self.cond.notify()

    def finish(self, done):
        """Send the last count, waiting 3 seconds for it at most: the result does not wait longer.
        (A report that comes after the result is ignored by Papex, so a late one does no harm.)"""
        with self.cond:
            self.done, self.final = done, True
            self.cond.notify()
        self.thread.join(3.0)
        with self.cond:
            self.closed = True
            self.cond.notify()

    def due(self):
        """Seconds until the next report may go (0: now), or None while there is nothing new."""
        if self.at is None or self.closed:
            return 0
        if self.final:
            # Papex keeps no report that comes less than a second after the one before it.
            return 0 if self.done == self.sent else max(0.0, self.at + 1.25 - time.monotonic())
        if self.done != self.sent:
            return max(0.0, self.at + PROGRESS_GAP - time.monotonic())
        return None

    def loop(self):
        while True:
            with self.cond:
                wait = self.due()
                while wait != 0:
                    self.cond.wait(wait)
                    wait = self.due()
                if self.closed or (self.final and self.ok and self.done == self.sent):
                    return
                done, final = self.done, self.final
                self.sent, self.at = done, time.monotonic()
            try:
                self.kit.request("POST", "/progress", json.dumps({"done": done}).encode(), PROGRESS_TIMEOUT)
                self.ok = True
            except Exception as e:  # a report must never stop the run
                self.ok = False
                if not self.failed and not self.closed:
                    self.failed = True
                    why = e.why() if isinstance(e, KitError) else str(e)
                    say(f"Could not tell Papex how far the run is ({why}). The run goes on, and the result "
                        "is still sent at the end.")
            if final:
                return


def api_address(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")):
        return url.rstrip("/")
    stop("--api takes an https address, for example https://api.papex.org (http only on this computer).")


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def batch_of_key(key):
    """The batch a key was used for before on this computer, found by the key's SHA-256."""
    for name in sorted(os.listdir(WORK)) if os.path.isdir(WORK) else []:
        try:
            if key_hash(key) in open(os.path.join(WORK, name, KEY_HASHES)).read().split():
                return name
        except OSError:
            continue
    return None


def fetch_batch(kit):
    """GET the batch and keep it as the batch file in its work folder; return that file's path."""
    try:
        body = kit.request("GET", "/batch")
    except KitError as e:
        if e.status == 401:
            lines = [f"The key was not accepted ({e.why()}). Copy the command again from your batch page "
                     "on papex.org and run it."]
            name = batch_of_key(kit.key)
            result = name and os.path.join(WORK, name, f"{name}.result.json")
            if result and os.path.exists(result):
                lines.append(f"The result file of batch {name} is here: {os.path.relpath(result)}")
                lines.append("  You can also upload it on the batch page by hand.")
            stop("\n".join(lines))
        if e.status == 409:
            stop(f"This batch no longer takes a result ({e.why()}). Nothing was run.")
        if e.status is None:
            stop(f"Papex could not be reached ({e.why()}). Check the connection and run the same "
                 "command again.")
        stop(f"Papex did not give the batch ({e.why()}). Run the same command again later.")
    try:
        name = json.loads(body).get("batch")
    except (ValueError, AttributeError):
        name = None
    if not re.match(r"^b-[0-9a-f]{6,10}$", str(name)):
        stop("Papex did not send a batch file. Run the same command again later.")
    work = os.path.join(WORK, name)
    os.makedirs(work, exist_ok=True)
    path = os.path.join(work, f"{name}.json")
    with open(path, "wb") as fh:
        fh.write(body)
    hashes = os.path.join(work, KEY_HASHES)
    if not os.path.exists(hashes) or key_hash(kit.key) not in open(hashes).read().split():
        with open(hashes, "a") as fh:
            fh.write(key_hash(kit.key) + "\n")
    return path


def send_result(kit, path):
    """PUT the result file's bytes as they are on disk, and say what comes next either way.
    True when Papex took it."""
    with open(path, "rb") as fh:
        body = fh.read()
    try:
        answer = kit.request("PUT", "/result", body, 60.0)
    except (KitError, KeyboardInterrupt) as e:
        why = e.why() if isinstance(e, KitError) else "stopped"
        print(f"  It was not sent ({why}).")
        if getattr(e, "status", None) == 409:
            print("  This batch no longer takes a result, on the batch page either.")
        else:
            print("  Upload it on your batch page on papex.org, choose how you are shown, and send it.")
        return False
    print("  Sent to Papex. Go back to your batch page, choose how you are shown, and press Send.")
    try:
        page = json.loads(answer).get("pagePath")
    except (ValueError, AttributeError):
        page = None
    if isinstance(page, str) and re.match(r"^/[\w/.-]{1,200}$", page):
        print(f"  {'https://papex.org' + page if kit.api == DEFAULT_API else page}")
    return True


def arg(name, default, cast=str):
    if name not in sys.argv:
        return default
    at = sys.argv.index(name) + 1
    if at >= len(sys.argv):
        stop(f"{name} needs a value after it.")
    return cast(sys.argv[at])


def positional():
    """The arguments that are neither options nor the values of options."""
    found, skip = [], False
    for a in sys.argv[1:]:
        if skip:
            skip = False
        elif a in ("--key", "--api", "--workers", "--agent-host"):
            skip = True
        elif not a.startswith("-"):
            found.append(a)
    return found


def main():
    if sys.version_info < (3, 9):
        stop("Python 3.9 or later is needed.")
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        stop(__doc__)
    check = "--check" in sys.argv
    key = arg("--key", None)
    files = positional()
    kit = None
    if not check:
        if any(f.startswith("swk_") for f in files):
            stop("This looks like a kit key. Put --key before it, as in the command on your batch page:\n"
                 "  python3 shared-work/run_batch.py --key <kit key>")
        if key is not None and files:
            stop("Give the key or a batch file, not both. With --key the kit fetches the batch from "
                 "Papex; with a batch file it sends nothing.")
        if key is None and not files:
            stop("Give the key or a batch file. Your batch page on papex.org shows the command to copy:\n"
                 "  python3 shared-work/run_batch.py --key <kit key>\n"
                 "  python3 shared-work/run_batch.py ~/Downloads/<batch file>")
        if key is not None:
            if not KEY_RE.match(key):
                stop("This is not a kit key. Copy the command again from your batch page on papex.org.")
            kit = Kit(api_address(arg("--api", DEFAULT_API)), key)
            print("With the key, this run tells Papex how many units are done and sends the result "
                  "file at the end. Nothing else leaves this computer.", flush=True)
    os.makedirs(WORK, exist_ok=True)
    tools = find_tools()
    tests = self_test(tools)
    print(f"CaDiCaL {tools['cadical_version']}: self-test {tests['cadical']}. "
          f"lrat-check ({CHECKER_VERSION}): self-test {tests['lrat-check']}.", flush=True)
    if "failed" in tests.values():
        stop("A tool failed its self-test, so nothing was run. Check the CaDiCaL version (1.9.0 or "
             "later) and build checker/lrat-check again from a fresh copy of the repository.")
    top = tree.ensure_top_cnf()
    if check:
        print("This computer is ready. Take units on the list's page on papex.org and run the "
              "command your batch page shows.")
        return

    batch_path = fetch_batch(kit) if kit else files[0]
    batch = load_batch(batch_path)
    workers = arg("--workers", max(1, (os.cpu_count() or 2) // 2), int)
    agent_host = arg("--agent-host", "").strip()
    if agent_host and not AGENT_HOST_RE.match(agent_host):
        stop("--agent-host takes a name of at most 80 letters, digits, spaces and . _ - + ( ) / :")
    manifest = load_manifest(batch["listSha256"])
    unknown = [u["key"] for u in batch["units"] if u["key"] not in manifest]
    if unknown:
        stop(f"The batch names units that are not in its list, for example {unknown[0]}.")

    key = batch["batch"]
    work = os.path.join(WORK, key)
    for sub in ("tmp", "proofs", "models"):
        os.makedirs(os.path.join(work, sub), exist_ok=True)
    log = os.path.join(work, "units.jsonl")
    records = {}
    if os.path.exists(log):
        for line in open(log):
            r = json.loads(line)
            records[r["key"]] = r
    keep = {u["key"] for u in batch["units"] if u.get("keepProof")}

    def finished(k):
        r = records.get(k)
        if not r or r["outcome"] not in ("UNSAT", "SAT"):
            return False
        needs_proof = r["outcome"] == "UNSAT" and (k in keep or r.get("check") != "VERIFIED")
        return not needs_proof or os.path.exists(os.path.join(work, "proofs", k.replace(":", "_") + ".lrat"))

    todo = [u for u in batch["units"] if not finished(u["key"])]
    total = len(batch["units"])
    expected = sum(manifest[u["key"]].get("expectedSeconds", 30) for u in todo)
    print(f"Batch {key}: {total} units, {len(keep)} marked to keep their proofs, "
          f"{total - len(todo)} already done.", flush=True)
    if todo:
        print(f"Running {len(todo)} units with {workers} worker{'s' if workers != 1 else ''}; "
              f"about {max(1, round(expected / workers / 60))} min on a computer like the one of the "
              "original run. Stop with Ctrl-C and run the same command again to continue.", flush=True)
    nice = ["nice", "-n", "10"] if shutil.which("nice") else []
    done = total - len(todo)
    finished_count = done
    progress = Progress(kit, finished_count) if kit else None
    pool = ThreadPoolExecutor(workers)
    try:
        with open(log, "a") as out:
            for fut in as_completed([pool.submit(run_unit, u, top, manifest, work, tools, nice)
                                     for u in todo]):
                r = fut.result()
                if r["outcome"] == "INPUT_MISMATCH":
                    stop(f"The formula built here for unit {r['key']} is not the list's. This copy of "
                         "the repository differs from the published one; use a fresh copy.")
                records[r["key"]] = r
                out.write(json.dumps(r) + "\n")
                out.flush()
                done += 1
                shown = {"UNSAT": "no solution, proof " + r.get("check", "").lower(),
                         "SAT": "A SOLUTION WAS FOUND", "UNKNOWN": "not finished"}[r["outcome"]]
                say(f"[{done}/{total}] {r['key']}: {shown}, {r.get('seconds', 0)} s")
                if progress and r["outcome"] in ("UNSAT", "SAT"):
                    finished_count += 1
                    progress.update(finished_count)
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        with running_lock:
            for p in list(running):
                p.kill()
        stop("\nStopped. Run the same command again to continue.")
    pool.shutdown()

    sat = [k for k, r in records.items() if r["outcome"] == "SAT"]
    failed = [k for k, r in records.items() if r["outcome"] == "UNSAT" and r["check"] != "VERIFIED"]
    open_units = [u["key"] for u in batch["units"] if not finished(u["key"])]
    if progress:
        progress.finish(total - len(open_units))
    if open_units:
        stop(f"{len(open_units)} units did not finish (for example {open_units[0]}). "
             "Run the same command again; no result file was written.")

    result = result_file(batch, records, tools, tests, agent_host)
    text = json.dumps(result, indent=1) + "\n"
    if len(text.encode()) > RESULT_MAX_BYTES:
        text = json.dumps(result, separators=(",", ":")) + "\n"
    result_path = os.path.join(work, f"{key}.result.json")
    with open(result_path, "w") as fh:
        fh.write(text)
    # The same file next to the batch file, where the batch page's file chooser opens.
    shown_path = os.path.relpath(result_path)
    beside = os.path.join(os.path.dirname(os.path.abspath(batch_path)), f"{key}.result.json")
    if os.path.abspath(beside) != os.path.abspath(result_path):
        try:
            with open(beside, "w") as fh:
                fh.write(text)
            shown_path = beside
        except OSError:
            pass
    kept = [u["key"] for u in batch["units"] if u["key"] in keep and records[u["key"]]["outcome"] == "UNSAT"]
    print()
    verified = sum(1 for r in records.values() if r.get("check") == "VERIFIED")
    print(f"Done: {verified} of {total} units have no solution, each with a checked proof.")
    print(f"Result file:  {shown_path}")
    sent = True
    if kit:
        sent = send_result(kit, result_path)
    else:
        print("  Upload it on your batch page on papex.org, choose how you are shown, and send it.")
    if kept:
        archive = bundle(work, key, kept, records)
        print(f"Kept proofs:  {os.path.relpath(archive)} "
              f"({len(kept)} proof{'s' if len(kept) != 1 else ''}, {os.path.getsize(archive) / 1e6:.1f} MB)")
        print("  Keep this file. If Papex Labs asks for the proofs, put it at a direct https link and\n"
              "  give that link for each marked unit on the batch page.")
    if failed:
        print(f"\nNOTE: the checker did not verify the proof of {len(failed)} unit(s): {', '.join(failed[:5])}.\n"
              f"Their proofs are in {os.path.relpath(os.path.join(work, 'proofs'))}. Please keep them and "
              "open an issue at https://github.com/papexlabs/kobon-triangles/issues: this needs a look by a person.")
    if sat:
        print(f"\nNOTE: CaDiCaL found a solution for {len(sat)} unit(s): {', '.join(sat[:5])}.\n"
              "That would contradict the published result, so it is far more likely a fault of this run "
              f"than a discovery. Please keep {os.path.relpath(os.path.join(work, 'models'))} and open an issue at "
              "https://github.com/papexlabs/kobon-triangles/issues.")
    if not sent:
        sys.exit(1)


if __name__ == "__main__":
    main()
