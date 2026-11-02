"""Race one more split against last-level cubes whose direct solve is still running.

For each cube given as NODE_DIR:INDEX, split it once more into NODE_DIR/c{INDEX} with
conquer.split (march_cu, then the cover check) and solve the sub-cubes with streamed LRAT
checks on the free cores. Whichever finishes first closes the cube:
  - every sub-cube UNSAT with check VERIFIED and cover=VERIFIED: the direct cadical run of the
    cube is stopped, conquer records it UNKNOWN, and summary.py counts it closed through c{INDEX};
  - the direct run ends UNSAT with check VERIFIED: the split's remaining sub-cubes are dropped.
A SAT sub-cube stops everything (it would make the whole formula satisfiable).

Run from the repository root, like conquer.py:
  python3 -I scripts/race_split.py WORKERS DEPTH NODE_DIR:INDEX [...] [--dry]
"""

import json
import os
import resource
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_cubes import read_cnf, read_cubes, solve_cube  # noqa: E402
from conquer import split  # noqa: E402


def log(msg):
    print(time.strftime("%F %T"), msg, flush=True)


def latest(path):
    """Latest record per cube; tolerates a line that conquer is still writing."""
    rs = {}
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                rs[r["cube"]] = r
    return rs


def closed_rec(r):
    return r is not None and r["status"] == "UNSAT" and r.get("check") == "VERIFIED"


def cadical_pids(match):
    """PIDs of cadical processes with an argument for which match(arg) is true."""
    pids = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            with open(f"/proc/{p}/cmdline", "rb") as fh:
                argv = fh.read().split(b"\0")
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == b"cadical" \
                and any(match(a.decode(errors="replace")) for a in argv[1:]):
            pids.append(int(p))
    return pids


def stop(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def main():
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, min(hard, 65536)), hard))
    except (ValueError, OSError):
        pass
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry"]
    workers, depth = int(args[0]), int(args[1])
    targets = []
    for spec in args[2:]:
        d, i = spec.rsplit(":", 1)
        targets.append((d.rstrip("/"), int(i)))

    def direct(d, i):
        path = os.path.join(d, f"cube{i}.cnf")
        return cadical_pids(lambda a: a == path)

    for d, i in targets:
        log(f"target {d} cube {i}: direct pids {direct(d, i)}, "
            f"record {latest(os.path.join(d, 'results.jsonl')).get(i)}, "
            f"split dir exists {os.path.exists(os.path.join(d, f'c{i}'))}")
    if dry:
        return

    # 1. split every target (in parallel; march_cu and the cover check are single-threaded)
    nodes = {}
    with ThreadPoolExecutor(len(targets)) as ex:
        futs = {}
        for d, i in targets:
            cubes = read_cubes(os.path.join(d, "sub.icnf"))
            futs[ex.submit(split, os.path.join(d, f"c{i}"), os.path.join(d, "cube.cnf"),
                           cubes[i], depth)] = (d, i)
        for fut in as_completed(futs):
            d, i = futs[fut]
            child = os.path.join(d, f"c{i}")
            cube_cnf, sub = fut.result()
            cov = open(os.path.join(child, "cover.out")).read().strip()
            n = len(read_cubes(sub))
            log(f"split {child}: {n} sub-cubes, {cov}")
            if "cover=VERIFIED" not in cov:
                log(f"COVER NOT VERIFIED in {child}: this target is left to its direct run")
                continue
            nodes[(d, i)] = (child, cube_cnf, read_cubes(sub))

    # 2. solve the sub-cubes, round-robin over the targets
    cnf_cache = {}
    lock = threading.Lock()
    state = {"sat": False}

    def resolved(key):
        d, i = key
        child, _, subs = nodes[key]
        if closed_rec(latest(os.path.join(d, "results.jsonl")).get(i)):
            return "direct"
        rs = latest(os.path.join(child, "results.jsonl"))
        if all(closed_rec(rs.get(j)) for j in range(len(subs))):
            return "split"
        return None

    def task(key, j):
        if state["sat"] or resolved(key):
            return key, None
        child, cube_cnf, subs = nodes[key]
        try:
            with lock:
                if cube_cnf not in cnf_cache:
                    cnf_cache[cube_cnf] = read_cnf(cube_cnf)
                hdr = cnf_cache[cube_cnf]
            return key, solve_cube(*hdr, subs[j], child, j, 0, True, True)
        except Exception as e:  # never let one task end the run silently
            return key, {"cube": j, "status": "ERROR", "error": repr(e)}

    order = []
    for j in range(max(len(v[2]) for v in nodes.values())):
        for key, (_, _, subs) in nodes.items():
            if j < len(subs):
                order.append((key, j))
    log(f"solving {len(order)} sub-cubes with {workers} workers")
    done = {}
    files = {}
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(task, key, j) for key, j in order]
        for fut in as_completed(futs):
            try:
                key, rec = fut.result()
            except Exception as e:
                log(f"task error: {e!r}")
                continue
            if rec is None:
                continue
            child = nodes[key][0]
            if rec["status"] == "ERROR":
                log(f"!! {child} sub-cube {rec['cube']}: {rec['error']}")
                continue
            if child not in files:
                files[child] = open(os.path.join(child, "results.jsonl"), "a")
            files[child].write(json.dumps(rec) + "\n")
            files[child].flush()
            if rec["status"] == "SAT":
                log(f"!! SAT in {child} sub-cube {rec['cube']}: stop")
                state["sat"] = True
                stop(cadical_pids(lambda a: any(a.startswith(c + "/cube")
                                                for c, _, _ in nodes.values())))
            elif rec["status"] == "UNSAT" and rec.get("check") != "VERIFIED":
                log(f"!! {child} sub-cube {rec['cube']}: {rec}")
            if key not in done:
                how = resolved(key)
                if how == "split":
                    pids = direct(*key)
                    log(f"CLOSED by split: {child} (all sub-cubes UNSAT VERIFIED); "
                        f"stopping direct run {pids}")
                    stop(pids)
                    done[key] = how
                elif how == "direct":
                    pids = cadical_pids(lambda a, c=child: a.startswith(c + "/cube"))
                    log(f"CLOSED by direct run: {key[0]} cube {key[1]}; "
                        f"stopping {len(pids)} split solves")
                    stop(pids)
                    done[key] = how
    for fh in files.values():
        fh.close()
    log(f"finished: {done}")


if __name__ == "__main__":
    main()
