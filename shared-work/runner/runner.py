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


def recheck(batch, result, manifest_name, command):
    """Run recheck_proofs.py on the marked units: {key: {"result", "checkedWith", "detail"}}."""
    declared = {u["key"]: u["proof"] for u in result["units"]}
    job = {"manifest": manifest_name, "units": [
        {"key": u["key"], "url": u["proofUrl"], "sha256": declared[u["key"]]["sha256"],
         "bytes": declared[u["key"]]["bytes"]} for u in batch["units"] if u["keepProof"]]}
    with tempfile.TemporaryDirectory(prefix="papex-job-") as jobdir:
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


def decide(batch, known, today, command):
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
        sent = datetime.datetime.fromisoformat(batch["submittedAt"].replace("Z", "+00:00")).date()
        return "proof-request", {"verdictId": str(uuid.uuid4()),
                                 "dueOn": (sent + datetime.timedelta(days=PROOF_DAYS)).isoformat(), "message": None}
    if state != "PROOFS_SUPPLIED":
        return None
    checks = recheck(batch, result, manifest_name, command)
    kept = [u["key"] for u in batch["units"] if u["keepProof"]]
    done = [{"key": k, "result": checks[k]["result"], "checkedWith": checks[k]["checkedWith"]}
            for k in kept if checks.get(k, {}).get("result") in ("VERIFIED", "FAILED")]
    if any(c["result"] == "FAILED" for c in done):
        return rejection(batch, result, "PROOF_FAILED", "A marked proof did not pass the check again.",
                         "Please keep the proof and open an issue at https://github.com/papexlabs/kobon-triangles/issues.", done)
    if len(done) < len(kept):
        missing = [k for k in kept if checks.get(k, {}).get("result") != "VERIFIED"]
        print(f"{batch['batchKey']}: no usable proof at the link of {', '.join(missing)}: "
              f"{checks.get(missing[0], {}).get('detail')}")
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
        batch = api.call("GET", f"/api/admin/shared-work/batches/{entry['batchKey']}")
        decision = decide(batch, known, today, args.recheck_cmd)
        if decision is None:
            print(f"{batch['batchKey']} {batch['state']}: no decision now")
            continue
        route, body = decision
        print(f"{batch['batchKey']} {batch['state']}: {route} "
              f"{body.get('outcome') or body.get('dueOn')} {body.get('reasonCode') or ''}")
        if args.post:
            api.call("POST", f"/api/admin/shared-work/batches/{batch['batchKey']}/{route}", body)
        else:
            print(json.dumps(body, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
