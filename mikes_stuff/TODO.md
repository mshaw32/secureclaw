# TODO

## High Priority

- Run a fresh end-to-end deployment test on a brand new Ubuntu CT using the GitHub `dev` branch flow.
- Confirm that `install.sh`, `vps-setup`, and `vps-post-setup` all pull the expected updated code from GitHub.
- Verify final report on fresh CT shows `OpenClaw: Running`.
- Verify no onboarding is triggered automatically anywhere in the setup flow.

## Deployment Follow-Up

- Decide whether `install.sh` should remain explicit-branch only, or whether a safer env-var fallback should be added later.
- Confirm whether any README/docs/install snippets need to be updated to show the correct `dev` testing command.
- Check whether `CLOUD_PROVIDER_GUIDES.md` or `README.md` should document branch-specific test usage.

## Fork Workflow

- Keep `mikes_stuff/` updated during every work session.
- Decide later whether to keep `mikes_stuff/` only on fork branches and exclude from upstream PR branches.
- Before opening upstream PRs, verify `mikes_stuff/` is not accidentally included.

## Nice To Have

- Add a lightweight diagnostic mode or extra logging around OpenClaw setup so future failures are easier to root-cause quickly.
- Consider documenting the expected OpenClaw gateway service behavior in comments near the install logic.
- Consider whether the security-check scripts should report service warm-up separately from service failure.

## Ideas / Recommendations

- Use commit-sized milestones consistently, as done in this session.
- Keep real CT validation notes in `WORKLOG.md` immediately after testing.
- If future sessions span multiple machines, read `HANDOFF.md`, then `WORKLOG.md`, then `TEST-NOTES.md` before making changes.
