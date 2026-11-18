#!/usr/bin/env python3
"""Decide the batches of the Kobon shared-work list. Papex Labs runs this; nobody accepts a unit by hand.

  PAPEX_SHARED_WORK_RUNNER_TOKEN=… python3 shared-work/runner/runner.py [--post] [--api URL]
                                           [--list KEY] [--recheck-cmd "docker run …"]

Without --post it only prints what it would send. The rules, the same for every batch:

1. A sent batch is read. It is rejected if a tool is not the list's (the patched lrat-check by its
   source SHA-256, CaDiCaL 1.9.0 or later), a tool's self-test is missing or failed, a unit's
   formula is not the manifest's, a unit is not "no solution, proof verified", or the reported time
   is not plausible (less than a fiftieth of the original run's).
2. Otherwise the proofs of the marked units are asked for, due 14 days after the batch was sent.
   When the kit sent the proofs to Papex with the batch's key, nobody is asked for a link: the
   request leaves the batch ready at once, and the runner fetches that stored file with its token
   and goes on to step 3 in the same run.
3. When every marked unit has a link, recheck_proofs.py fetches and checks the proofs again. With
   --recheck-cmd it runs in a container: {job} in the command is a directory that holds job.json
   and receives out.json, for example
     --recheck-cmd "docker run --rm --memory 6g --cpus 2 -v {job}:/job kobon-recheck"
   All verified: the batch is accepted. A proof that fails: the batch is rejected. A link that
   gives nothing usable: the batch waits, so the participant can correct the link, until the due
   date; after that it is rejected.
4. A unit reported as solved (a solution found) rejects the batch and prints ALERT: a person looks
   at it and at the list. Nothing is published by this program.

The token is read from the environment, sent as X-Papex-Runner-Token and never printed. The
re-check gets no credential: it reads a job file and writes outcomes.
"""

import argparse
import datetime
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, KIT)
import tree  # noqa: E402

TOKEN_ENV = "PAPEX_SHARED_WORK_RUNNER_TOKEN"
CHECKER_SHA256 = "0x" + tree.sha256_file(os.path.join(tree.ROOT, "checker", "lrat-check.c"))
PROOF_DAYS = 14
STORED_WAIT = datetime.timedelta(minutes=15)   # how long a sent batch may still receive the kit's proofs
STORED_NAME = "proofs.tar.xz"        # the kit's archive, fetched from Papex into the job directory
STORED_MAX_BYTES = 200 * 1024 * 1024   # Papex takes less; a longer answer is refused
TIMING_FACTOR = 50
SELF = "the participant's run with the patched lrat-check"


class Api:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "papex-shared-work-runner")
        request.add_header("X-Papex-Runner-Token", self.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode() or "null")
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{method} {path} answered {error.code}: {error.read().decode('utf-8', 'replace')[:500]}")

    def download(self, path, dest, expected_sha256, limit):
        """GET a file with the token to dest; refuse one that is too long or not the one Papex names."""
        request = urllib.request.Request(self.base + path, method="GET")
        request.add_header("User-Agent", "papex-shared-work-runner")
        request.add_header("X-Papex-Runner-Token", self.token)
        digest, size = hashlib.sha256(), 0
        try:
            with urllib.request.urlopen(request, timeout=120) as response, open(dest, "wb") as out:
                for block in iter(lambda: response.read(1 << 20), b""):
                    size += len(block)
                    if size > limit:
                        raise SystemExit(f"GET {path}: the stored proofs are longer than {limit} bytes; nothing was decided")
                    digest.update(block)
                    out.write(block)
        except urllib.error.HTTPError as error:
            raise SystemExit(f"GET {path} answered {error.code}: {error.read().decode('utf-8', 'replace')[:300]}")
        if "0x" + digest.hexdigest() != expected_sha256:
            raise SystemExit(f"GET {path}: the file is not the one Papex names; nothing was decided")

    def queue(self, list_key):
        page = 0
        while True:
            query = {"state": "SUBMITTED,PROOFS_REQUESTED,PROOFS_SUPPLIED", "page": page, "size": 100}
            if list_key:
                query["list"] = list_key
            answer = self.call("GET", "/api/admin/shared-work/batches?" + urllib.parse.urlencode(query))
            yield from answer["content"]
            page += 1
            if page >= answer["totalPages"]:
                return


def manifests():
    """Every manifest of this repository: list sha256 -> (file name, unit key -> line)."""
    found = {}
    for name in sorted(os.listdir(KIT)):
        if name.endswith(".manifest.ndjson"):
            path = os.path.join(KIT, name)
            found["0x" + tree.sha256_file(path)] = (name, {u["key"]: u for u in map(json.loads, open(path))})
    return found


def version_ok(text):
    parts = text.split(".")
    try:
        return tuple(int(p) for p in parts[:3]) >= (1, 9, 0)
    except ValueError:
        return False


def check_static(result, manifest):
    """None when the result file passes, else (reason code, text for the participant, next step)."""
    again = "Update the repository (git pull), take units again and run the kit as it is."
    tools = {t.get("name"): t for t in result.get("env", {}).get("tools", [])}
    checker, solver = tools.get("lrat-check"), tools.get("cadical")
    if not checker or checker.get("sourceSha256") != CHECKER_SHA256:
        return "TOOL_NOT_ALLOWED", "The checker of this run is not the list's patched lrat-check.", again
    if not solver or not version_ok(solver.get("version", "")):
        return "TOOL_NOT_ALLOWED", "The solver of this run is not CaDiCaL 1.9.0 or later.", again
    for tool in (checker, solver):
        if tool.get("selfTest") is None or tool.get("selfTest") == "absent":
            return "SELF_TEST_MISSING", f"The result reports no self-test of {tool['name']}.", again
        if tool.get("selfTest") != "passed":
            return "SELF_TEST_FAILED", f"The self-test of {tool['name']} failed on this computer.", again
    seconds = expected = 0.0
    for unit in result["units"]:
        line = manifest.get(unit["key"])
        if line is None:
            return "INPUT_HASH_MISMATCH", f"Unit {unit['key']} is not in the list.", again
        if unit["outcome"] != "UNSAT":
            return "OUTCOME_UNEXPECTED", (f"Unit {unit['key']} is reported as solved. A person at Papex Labs "
                                          "looks at this before anything else happens."), \
                "Please keep the files of this run and open an issue at https://github.com/papexlabs/kobon-triangles/issues."
        if (unit.get("extra") or {}).get("inputSha256") != line["inputSha256"]:
            return "INPUT_HASH_MISMATCH", f"The formula of unit {unit['key']} is not the list's.", again
        if {"tool": "lrat-check", "result": "VERIFIED"} not in (unit.get("checks") or []):
            return "NOT_VERIFIED", f"The checker did not verify the proof of unit {unit['key']}.", \
                "Please keep the proof and open an issue at https://github.com/papexlabs/kobon-triangles/issues."
        seconds += unit["seconds"]
        expected += line.get("expectedSeconds", 1)
    if seconds * TIMING_FACTOR < expected:
        return "TIMING_IMPLAUSIBLE", "The reported running time is far below what these units take.", again
    return None


def recheck(batch, result, manifest_name, command, api=None):
    """Run recheck_proofs.py on the marked units: {key: {"result", "checkedWith", "detail"}}.

    The proofs come from the links the participant gave, or, when the kit sent them to Papex with
    the batch's key, from that stored file: the runner fetches it with its token into the job
    directory, and the re-check (which holds no credential) reads it from there."""
    declared = {u["key"]: u["proof"] for u in result["units"]}
    stored = batch.get("storedProofs")
    source = {"stored": STORED_NAME} if stored else None
    job = {"manifest": manifest_name, "units": [
        dict(source or {"url": u["proofUrl"]}, key=u["key"], sha256=declared[u["key"]]["sha256"],
             bytes=declared[u["key"]]["bytes"]) for u in batch["units"] if u["keepProof"]]}
    with tempfile.TemporaryDirectory(prefix="papex-job-") as jobdir:
        if stored:
            api.download(f"/api/admin/shared-work/batches/{batch['batchKey']}/proofs",
                         os.path.join(jobdir, STORED_NAME), stored["sha256"], STORED_MAX_BYTES)
        with open(os.path.join(jobdir, "job.json"), "w") as fh:
            json.dump(job, fh)
        if command:
            cmd = [part.replace("{job}", jobdir) for part in shlex.split(command)]
        else:
            cmd = [sys.executable, os.path.join(HERE, "recheck_proofs.py"),
                   os.path.join(jobdir, "job.json"), os.path.join(jobdir, "out.json")]
        env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV}
        if subprocess.run(cmd, env=env).returncode != 0:
            raise SystemExit("the re-check did not finish; nothing was decided")
        return json.load(open(os.path.join(jobdir, "out.json")))


def units_body(result, accepted, kept_with):
    out = []
    for unit in result["units"]:
        if not accepted:
            out.append({"key": unit["key"], "verdict": "NOT_ACCEPTED", "reason": "BATCH_REJECTED", "checkedWith": None})
        else:
            with_ = kept_with.get(unit["key"])
            out.append({"key": unit["key"], "verdict": "ACCEPTED", "reason": None,
                        "checkedWith": f"{SELF}; proof checked again by Papex Labs ({with_})" if with_ else SELF})
    return out


def rejection(batch, result, code, text, next_step, keep_checks=()):
    return "verdict", {"verdictId": str(uuid.uuid4()), "expectedState": batch["state"], "outcome": "REJECTED",
                       "reasonCode": code, "reasonText": text, "nextStepText": next_step, "summaryText": None,
                       "units": units_body(result, False, {}), "keepChecks": list(keep_checks)}


def decide(batch, known, today, command, api=None, now=None):
    """The one decision for a batch in its current state: (route, body), or None to leave it."""
    result = json.loads(batch["resultText"])
    entry = known.get(batch["list"]["sha256"])
    if entry is None:
        return None  # not a list of this repository
    manifest_name, manifest = entry
    state = batch["state"]
    due = batch.get("proofsDueAt") and datetime.datetime.fromisoformat(
        batch["proofsDueAt"].replace("Z", "+00:00")).date()
    failure = check_static(result, manifest)
    if failure and failure[0] == "OUTCOME_UNEXPECTED":
        print(f"ALERT {batch['batchKey']}: a unit is reported as solved. Look at this batch and the list.")
    if state == "PROOFS_REQUESTED":
        if today > due:
            return rejection(batch, result, "PROOFS_NOT_SUPPLIED", "The proofs were not linked in time.",
                             "Take units again to run them again.")
        return None
    if failure:
        return rejection(batch, result, *failure)
    if state == "SUBMITTED":
        sent_at = datetime.datetime.fromisoformat(batch["submittedAt"].replace("Z", "+00:00"))
        # The kit sends the marked proofs after the result, and a person may press Send while they
        # are still going up. Asking at once would send them an email for a link nobody needs: the
        # request waits until the kit has had its time. (Only a Papex that can hold proofs says
        # "storedProofs" at all; without the word nothing is waited for.)
        waited = (now or datetime.datetime.now(datetime.timezone.utc)) - sent_at
        if "storedProofs" in batch and not batch["storedProofs"] and waited < STORED_WAIT \
                and any(u["keepProof"] for u in batch["units"]):
            print(f"{batch['batchKey']}: sent {int(waited.total_seconds() // 60)} min ago and the kit's proofs are "
                  f"not with Papex yet; the proof request waits {int(STORED_WAIT.total_seconds() // 60)} min for them")
            return None
        return "proof-request", {"verdictId": str(uuid.uuid4()),
                                 "dueOn": (sent_at.date() + datetime.timedelta(days=PROOF_DAYS)).isoformat(), "message": None}
    if state != "PROOFS_SUPPLIED":
        return None
    checks = recheck(batch, result, manifest_name, command, api)
    kept = [u["key"] for u in batch["units"] if u["keepProof"]]
    done = [{"key": k, "result": checks[k]["result"], "checkedWith": checks[k]["checkedWith"]}
            for k in kept if checks.get(k, {}).get("result") in ("VERIFIED", "FAILED")]
    if any(c["result"] == "FAILED" for c in done):
        return rejection(batch, result, "PROOF_FAILED", "A marked proof did not pass the check again.",
                         "Please keep the proof and open an issue at https://github.com/papexlabs/kobon-triangles/issues.", done)
    if len(done) < len(kept):
        missing = [k for k in kept if checks.get(k, {}).get("result") != "VERIFIED"]
        print(f"{batch['batchKey']}: no usable proof {'in the stored file' if batch.get('storedProofs') else 'at the link'}"
              f" of {', '.join(missing)}: {checks.get(missing[0], {}).get('detail')}")
        if due and today > due:
            return rejection(batch, result, "PROOF_UNREACHABLE", "A marked proof could not be fetched from its link.",
                             "Take units again and put the proofs file at a direct https link.", done)
        return None
    kept_with = {c["key"]: c["checkedWith"] for c in done}
    units = units_body(result, True, kept_with)
    tools = "; ".join(sorted(set(kept_with.values())))
    return "verdict", {"verdictId": str(uuid.uuid4()), "expectedState": "PROOFS_SUPPLIED", "outcome": "ACCEPTED",
                       "reasonCode": None, "reasonText": None, "nextStepText": None,
                       "summaryText": (f"{len(units)} units accepted. Papex Labs checked the {len(kept)} marked "
                                       f"proof{'s' if len(kept) != 1 else ''} again: all verified ({tools})."),
                       "units": units, "keepChecks": done}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Kobon shared-work acceptance runner")
    parser.add_argument("--api", default="https://api.papex.org")
    parser.add_argument("--list", default=None, help="only this list (key or id)")
    parser.add_argument("--post", action="store_true", help="send the decisions (default: print them)")
    parser.add_argument("--recheck-cmd", default=None,
                        help="command that runs recheck_proofs.py in isolation; {job} is the job directory, "
                             "which holds job.json and must receive out.json")
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise SystemExit(f"Set {TOKEN_ENV}.")
    api = Api(args.api, token)
    known = manifests()
    today = datetime.datetime.now(datetime.timezone.utc).date()
    for entry in api.queue(args.list):
        # A batch whose proofs the kit sent goes on in this same run: the proof request leaves it
        # PROOFS_SUPPLIED at once (nobody has a link to give), so it is read again and decided.
        for _ in range(2):
            batch = api.call("GET", f"/api/admin/shared-work/batches/{entry['batchKey']}")
            decision = decide(batch, known, today, args.recheck_cmd, api)
            if decision is None:
                print(f"{batch['batchKey']} {batch['state']}: no decision now")
                break
            route, body = decision
            print(f"{batch['batchKey']} {batch['state']}: {route} "
                  f"{body.get('outcome') or body.get('dueOn')} {body.get('reasonCode') or ''}"
                  + (" (proofs stored at Papex)" if batch.get("storedProofs") else ""))
            if not args.post:
                print(json.dumps(body, indent=1, ensure_ascii=False))
                break
            api.call("POST", f"/api/admin/shared-work/batches/{batch['batchKey']}/{route}", body)
            if route != "proof-request" or not batch.get("storedProofs"):
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
