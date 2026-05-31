# TODO

## High Priority

- Run a fresh end-to-end deployment test on a brand new Ubuntu CT using the GitHub `dev` branch flow.
- Confirm that `install.sh`, `vps-setup`, and `vps-post-setup` all pull the expected updated code from GitHub.
- Verify final report on fresh CT shows `OpenClaw: Installed`.
- Verify no onboarding is triggered automatically anywhere in the setup flow.
- After setup completes, manually run `openclaw onboard` as the target user.
- Confirm the `openclaw05` Codex plugin/module error does not recur:
  - `openclaw/dist/plugin-sdk/root-alias.cjs/exec-approvals-runtime`

## Deployment Follow-Up

- Decide whether `install.sh` should remain explicit-branch only, or whether a safer env-var fallback should be added later.
- Confirm whether any README/docs/install snippets need to be updated to show the correct `dev` testing command.
- Check whether `CLOUD_PROVIDER_GUIDES.md` or `README.md` should document branch-specific test usage.
- If the restored streamed installer fixes onboarding, merge `dev` back into `main` again and push only to fork `origin`.
- If onboarding still fails, compare installed OpenClaw package/plugin versions and user npm paths on the failing CT against a known-good upstream install.

## Fork Workflow

- Keep `mikes_stuff/` updated during every work session.
- Decide later whether to keep `mikes_stuff/` only on fork branches and exclude from upstream PR branches.
- Before opening upstream PRs, verify `mikes_stuff/` is not accidentally included.

## Nice To Have

- Add a lightweight diagnostic mode or extra logging around OpenClaw setup so future failures are easier to root-cause quickly.
- Consider documenting that OpenClaw gateway setup is intentionally deferred to `openclaw onboard`.
- Consider whether the security-check scripts should report service warm-up separately from service failure.
- Consider adding a post-install diagnostic command to capture:
  - `openclaw -V`
  - `node -v`
  - `npm -v`
  - `command -v openclaw`
  - key OpenClaw npm install paths

## Ideas / Recommendations

- Use commit-sized milestones consistently, as done in this session.
- Keep real CT validation notes in `WORKLOG.md` immediately after testing.
- If future sessions span multiple machines, read `HANDOFF.md`, then `WORKLOG.md`, then `TEST-NOTES.md` before making changes.
