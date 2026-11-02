# Following the course step by step

Every lesson in "Become a Full-Stack AI Engineer" has a matching step in this repo.
Part 7 of the course is step `07`. Each step is one commit on the `course` branch,
tagged `step-07`, so you can open the exact code a lesson describes.

## Jump to a lesson's code

```bash
git fetch --tags
git checkout step-07          # the code exactly as Part 7 leaves it
```

`git checkout course` brings you back to the latest step.

## See what a lesson changed

```bash
git diff step-06 step-07      # everything Part 7 added or changed
git diff step-06 step-07 --stat
```

## Check your own work

Build the lesson yourself on your own branch, then run the step's checkpoint:

```bash
make check STEP=07
```

It runs that step's tests against your code. On a pass it prints
`✓ Part 07 checkpoint: <title> (<n> passed)`. On a failure it names the test files to
compare with the reference, for example `git diff step-07 -- tests/test_x.py`.

## What lives here

- `course/steps/NN.toml`: one manifest per step. It names the step's lesson, its
  checkpoint tests, the commands whose output the lesson quotes, and its screenshots.
- `course/outputs/NN/`: the captured output of those commands. The lessons quote these
  files, never hand-typed output.
- `course/tools/`: the scripts that check all of this. `python course/tools/steps.py
  verify` proves the step history is one clean chain.
