# Shared work: solve leaves of case B again

Case B of this proof is a tree with 67,614 leaves. Each leaf is a formula that a SAT solver showed
to have no solution, with a proof that a checker read. The checker of the original runs did not
check the last step of a proof (see the correction in the main [README](../README.md)), so for most
leaves that step still rests on the solver.

This list asks you to solve some of those leaves again on your own computer. Your solver writes a
proof for each leaf and the patched checker of this repository reads all of it, the last step
included. You need no mathematics for this: a laptop and about ten minutes are enough.

The first list, `pilot-v1`, has 2,000 leaves chosen at random among those that took at most 20
seconds in the original run (`pilot-v1.manifest.ndjson`; `make_manifest.py` writes the same file
again).

## Taking part

You need a Papex account, macOS or Linux (on Windows, WSL), Python 3.9 or later, git, a C compiler
and CaDiCaL 1.9.0 or later as `cadical` on the PATH (macOS: `brew install cadical`; otherwise build
it from [arminbiere/cadical](https://github.com/arminbiere/cadical)).

1. Set up the kit once:

   ```sh
   git clone https://github.com/papexlabs/kobon-triangles && cd kobon-triangles
   python3 shared-work/run_batch.py --check       # tests the tools, runs nothing
   ```

2. On [the list's page on papex.org](https://papex.org/problems/kobon-triangle-problem/shared-work),
   take units. You get a batch page.
3. Copy the command from your batch page and run it in the `kobon-triangles` folder. It looks
   like this, with a key for your batch:

   ```sh
   python3 shared-work/run_batch.py --key swk_…
   ```

   The kit fetches the batch's units, prints one line per unit and can be stopped and started
   again with the same command. The batch page shows how far it has got. At the end the kit
   sends the result file to the batch page. If the kit says the key is no longer valid, copy the
   command again.
4. Go back to the batch page, choose how you are shown, and send the batch.
5. Keep the proofs file the kit names at the end (`shared-work/work/b-948ffd/b-948ffd.proofs.tar.xz`
   for a batch named b-948ffd). It holds the proofs of the few units your batch marks. Papex Labs
   asks for them by email: put the file at a direct https link (a GitHub release, your own site, a
   Dropbox link ending in `dl=1`) and give that link for each marked unit on the batch page.

### With a batch file instead

If you want the kit to send nothing, download the batch file on the batch page and give its name
instead of the key:

```sh
python3 shared-work/run_batch.py ~/Downloads/b-948ffd.json
```

At the end the kit writes the result file next to the batch file (here
`~/Downloads/b-948ffd.result.json`). Upload it on the batch page, choose how you are shown, and
send the batch.

With an AI app connected to Papex you can ask it to take the units and, once you have downloaded
the batch file from the batch page, to run the kit and attach the result. Sending the batch, and
how your name is shown, stays with you on papex.org.

### What the kit sends

With the key, the kit sends Papex two things and nothing else: while it runs, how many units of
the batch are done; at the end, the result file. It never writes the key to a file or prints it.
With a batch file, the kit sends nothing anywhere. The result file holds the name of your
operating system and processor, the tool versions, and for each unit the running time and the size
and SHA-256 of its proof.

## How a batch is decided

No person accepts a unit by hand. `runner/runner.py` decides every batch by the same rules:

- The checker must be this repository's patched `lrat-check` (by the SHA-256 of its source) and
  the solver CaDiCaL 1.9.0 or later, and both must have passed the kit's self-test on your
  computer. The self-test includes the proof that the unpatched checker wrongly accepts.
- Every unit's formula must be the list's (SHA-256 in the manifest), and every unit must be "no
  solution, proof verified".
- The marked proofs are fetched from your link and checked again by Papex Labs
  (`runner/recheck_proofs.py`). One marked proof that fails rejects the whole batch.

An accepted unit is listed in the public ledger with what checked it: your run, and for the marked
units also Papex Labs' second check. Units that were not marked rest on your run. If a unit ever
comes out as solved, or a proof does not verify, the kit says so: please keep the files and open an
issue on this repository, because a person has to look at that.

## What this is not

The result of the paper, a(11) = 32, was proved first by Parpalak and Utkin and does not depend on
this list. The list is not peer review, and an accepted unit says only that one leaf was solved
again with a fully checked proof.
