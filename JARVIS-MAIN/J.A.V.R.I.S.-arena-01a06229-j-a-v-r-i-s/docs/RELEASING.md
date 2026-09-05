# Release process (for the owner)

1. **Decide the LICENSE** (owner-reserved; recommendation stands: Apache-2.0 or
   MIT). Until then, artifacts carry `LicenseRef-Proprietary-Until-Owner-Decides`
   and public redistribution is discouraged.
2. Bump `version` in `pyproject.toml` and `__version__` in
   `src/jarvis/__init__.py` (must match; a unit test enforces it), update
   `packaging/rpm/jarvis-agent.spec` + `packaging/arch/PKGBUILD`, add a
   CHANGELOG entry.
3. Commit on the working branch, then cut a tag:
   ```sh
   git tag v1.0.0 && git push origin v1.0.0
   ```
4. The `Release` workflow builds wheel + sdist + deb, smoke-tests the wheel in a
   clean venv, and opens a **draft** GitHub Release with all artifacts attached.
   Review, publish the draft when satisfied.
5. PyPI publishing is **manual and owner-only** (`twine upload dist/*` with your
   own account / trusted publisher). The agent never publishes.
6. To re-run any verification on fresh GitHub VMs on demand:
   **Actions → CI / Container eval / Packaging & install → Run workflow**
   (`workflow_dispatch` is enabled on all three).

## Tag-push mechanics (hard-won, 2026-09-04 — read before cutting tags)

- **Push tags ONE per `git push` event.** GitHub Actions creates *no* push
  events when more than three tags arrive at once — six tags in a single push
  fired zero Release runs, silently. Remedies, in order of preference: push
  each tag individually; or recycle (`git push origin :refs/tags/<t>` then
  re-push) one at a time.
- The project convention is **annotated `-rc1` tags at the CI-green commit**
  (`v1.2.1-rc1`, …, `v1.10.1-rc1`); final (non-rc) tags are cut by the owner
  when publishing. The Release workflow auto-creates the **draft** with
  artifacts; the agent then edits title/notes (`gh release edit --draft
  --prerelease --notes-file …`) with a "pending owner review" disclaimer.
  Publishing the draft is owner-only and `--draft` cannot publish by accident.
- **Docs-only changes ship WITHOUT a tag or release** (standing precedent): the rc-tag +
  draft-release pattern is for code milestones only.
- **Watch CI with bounded snapshots, never blocking watches.** A `gh run watch` on a
  freshly-pushed run blocks for the run's ENTIRE duration (10+ min for the matrix; serially
  watching 3 runs ≈ half an hour of dead air — happened 2026-09-05). Correct pattern: poll
  `gh run list` / `gh run view` snapshots every ~20–30 s and do other work between polls.
- **A stalled container leg is infra, not code — verify via the paired run.** The
  execution-eval step inside a packaging leg can hang 40+ min on a runner/image stall
  (ubuntu-24.04, 2026-09-05) while the same eval passes on every other distro in the same run
  and on the same commit's pull_request-triggered twin. `gh run rerun` is token-refused; the
  paired-run precedent (same commit, same workflow, different trigger) is the verification
  path — disclose it honestly in the release notes.
- The review queue stands at **22 drafts** (`v1.0.0-rc1` … `v1.18.0-rc1`; each draft +
  prerelease, 3 assets, unpublished). Publishing is owner-reserved and one at a time.
- `gh workflow run` (dispatch) may be unavailable to automation tokens
  (HTTP 403, no `actions:write`) — git push and `gh release edit` still work;
  plan around dispatch, not with it.
- CI legs that hit api.github.com run with `GITHUB_TOKEN` and fetch.py honors
  it (plus one bounded retry); if a `tests/test_knowledge_live.py` failure
  names rate-limiting, verify the paired run at the same commit before
  post-morteming — the flake class is known and now remediated (v1.10.2).
