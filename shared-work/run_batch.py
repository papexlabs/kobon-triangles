#!/usr/bin/env python3
"""Run a batch of the Kobon shared-work list on your own computer.

  python3 shared-work/run_batch.py BATCH_FILE [--workers N] [--agent-host NAME]
  python3 shared-work/run_batch.py --check

BATCH_FILE is the file you downloaded from your batch page on papex.org; the page shows this
command with the file's name. For every unit of the batch the kit writes the unit's formula, solves
it with CaDiCaL, which writes an LRAT proof, and checks that proof with the patched lrat-check of
this repository (checker/). It then writes two files in shared-work/work/BATCH/:

  BATCH.result.json     what you upload on the batch page; a copy is put next to BATCH_FILE
  BATCH.proofs.tar.xz   the proofs of the units the batch marks; keep it until the batch is decided

A stopped run continues where it stopped when you give the same command again. --check only tests
that the tools on this computer work. Nothing is sent anywhere by this program.

Needs Python 3.9 or later, a C compiler (cc) and CaDiCaL 1.9.0 or later as `cadical` on the PATH
(or named by the environment variable CADICAL). See shared-work/README.md.
"""

import hashlib
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
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tree  # noqa: E402
from run_cubes import lrat_verdict  # noqa: E402  (tree put scripts/ on the path)

BATCH_SCHEMA = "papex-shared-work-batch/v1"
RESULT_SCHEMA = "papex-shared-work-result/v1"
RESULT_MAX_BYTES = 262144
KIT_VERSION = "1"
CHECKER_SRC = os.path.join(tree.ROOT, "checker", "lrat-check.c")
CHECKER_VERSION = "drat-trim 2e3b2dc + empty-clause patch"
WORK = os.path.join(HERE, "work")
AGENT_HOST_RE = re.compile(r"^[\w ._+()/:-]{1,80}$")

# Pigeonhole: 4 pigeons do not fit in 3 holes. Small, unsatisfiable, and it needs real proof steps.
SELFTEST_UNSAT = "p cnf 12 22\n" + "".join(
    f"{3 * i + 1} {3 * i + 2} {3 * i + 3} 0\n" for i in range(4)) + "".join(
    f"-{3 * i + j + 1} -{3 * k + j + 1} 0\n" for j in range(3) for i in range(4) for k in range(i + 1, 4))
# drat-trim issue #42: the unpatched checker prints VERIFIED for this proof of a satisfiable formula.
SELFTEST_SAT = "p cnf 2 2\n1 2 0\n-1 2 0\n"
SELFTEST_BAD_PROOF = "3 0 0\n"

running = set()
running_lock = threading.Lock()


def stop(message):
    raise SystemExit(message)


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


def arg(name, default, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    if sys.version_info < (3, 9):
        stop("Python 3.9 or later is needed.")
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        stop(__doc__)
    os.makedirs(WORK, exist_ok=True)
    tools = find_tools()
    tests = self_test(tools)
    print(f"CaDiCaL {tools['cadical_version']}: self-test {tests['cadical']}. "
          f"lrat-check ({CHECKER_VERSION}): self-test {tests['lrat-check']}.", flush=True)
    if "failed" in tests.values():
        stop("A tool failed its self-test, so nothing was run. Check the CaDiCaL version (1.9.0 or "
             "later) and build checker/lrat-check again from a fresh copy of the repository.")
    top = tree.ensure_top_cnf()
    if sys.argv[1] == "--check":
        print("This computer is ready. Take units on the list's page on papex.org, download the "
              "batch file and run the command your batch page shows.")
        return

    batch = load_batch(sys.argv[1])
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
                print(f"[{done}/{total}] {r['key']}: {shown}, {r.get('seconds', 0)} s", flush=True)
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
    beside = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), f"{key}.result.json")
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


if __name__ == "__main__":
    main()
