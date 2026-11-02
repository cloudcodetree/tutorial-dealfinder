# Releasing the course

The `course` branch holds one `step-NN:` commit per lesson. At release it replaces
`main`, and every `step-NN` tag moves onto its step commit. Every remote change below
is marked **owner go: reply 'you do it'**: nobody runs it without that.

## The release model

| Phase | `main` | `course` | Tags |
|---|---|---|---|
| Before release | The product's source of truth. Production deploys from it. | A working branch, rebuilt freely. Pushing it, `--force-with-lease` included, is routine. | Remote `step-*` tags stay put. The site pins step commits by SHA, so it never needs tags. |
| At release | Replaced by `course`. The old `main` survives as the tag `archive/pre-course-v1`. | Its last step's tree equals the old `main` tree, which `release-check` proves. | `retag --apply --prune --push` moves every `step-NN`. `course-v1` marks the last step. |
| After release | Post-release work lands as ordinary commits after the last step. | Frozen. | Frozen. `retag` refuses while `course-v1` exists. A v2 picks its own tag namespace. |

A product bug found while building steps is fixed on `main` first, by PR. Then it is
folded into its step: `git commit --fixup=<step sha>` on `course`, then
`git rebase --autosquash --root`.

## Before you start

```bash
python course/tools/steps.py verify               # ✓ N steps, linear
python course/tools/steps.py retag --apply        # local tags only; nothing leaves the machine
```

## The sequence

1. Check everything holds. It prints the commands below with the real SHAs, and runs none:
   ```bash
   python course/tools/steps.py release-check
   ```
2. Keep the old `main` as a tag. **Owner go: reply 'you do it'.**
   ```bash
   git tag -a archive/pre-course-v1 origin/main -m 'main before course-v1'
   git push origin archive/pre-course-v1
   ```
3. Replace `main` with `course`. **Owner go: reply 'you do it'.**
   ```bash
   git push --force-with-lease=main origin course:main
   ```
4. Move every remote step tag, in one atomic push. **Owner go: reply 'you do it'.**
   ```bash
   python course/tools/steps.py retag --apply --prune --push
   ```
5. Mark the release. From here on the step tags are frozen. **Owner go: reply 'you do it'.**
   ```bash
   git tag -a course-v1 <last step sha> -m 'course v1'
   git push origin course-v1
   ```
