# Handoff Notes

This folder is for fork-only notes that sync between Mike's machines.

These files are not part of the upstream product. They are here so a future session can quickly answer:
- what we changed
- what is working
- what is still outstanding
- what command to use for testing
- where to resume work next

## Files

`WORKLOG.md`
- Running journal of work completed.
- Update this in real time during a session.
- Preferred minimum: update after each meaningful milestone.
- Strong preference: update after each commit, major test, root-cause discovery, or deployment result.

`TODO.md`
- Outstanding work, future ideas, follow-ups, cleanup items, recommendations, and risks.
- Keep items short and actionable.
- Mark items clearly when done or no longer needed.

`TEST-NOTES.md`
- Deployment/test instructions and known-good validation commands.
- Must include exact branch-sensitive commands.
- Update immediately when install/test flow changes.

## Update Rules

1. Update `WORKLOG.md` during the session, not hours later.
2. Update `TEST-NOTES.md` whenever commands, branch flow, or validation steps change.
3. Update `TODO.md` whenever new follow-up work or risks are discovered.
4. Before ending a session, make sure these notes reflect reality.
5. Before starting a new session on another machine, read these files first.

## PR Hygiene

These files are for Mike's fork and should not go upstream by accident.

Before opening an upstream PR:
- review whether `mikes_stuff/` is included
- if needed, prepare a clean PR branch without these files

## Current Working Branch

As of 2026-05-30, active branch:

`dev`

## Most Important Current Context

- The OpenClaw install failure on Proxmox Ubuntu CTs was reproduced and fixed.
- The fix was validated on real CT `openclaw03`.
- Setup intentionally installs OpenClaw CLI only; `openclaw onboard` will install/register the gateway service later.
- A later fresh CT test on `openclaw05` deployed successfully from fork `main`, but `openclaw onboard` failed with a Codex plugin/module error:
  - `Cannot find module ...openclaw/dist/plugin-sdk/root-alias.cjs/exec-approvals-runtime`
- Suspected cause was our temporary installer wrapper that downloaded `https://openclaw.ai/install.sh` as root to `/tmp/openclaw_install.sh` and ran that local script via `runuser -l`.
- Current `dev` now restores the upstream-style streamed OpenClaw installer invocation while keeping CT prerequisite hardening:
  - install dependencies as root
  - run `curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard` as the target user via `su -`
  - keep explicit `PATH` and dependency checks
- The key branch-flow gotcha is that testing `dev` requires passing `dev` to `install.sh`, not just downloading `install.sh` from the `dev` URL.
- Exact current test command is documented in `TEST-NOTES.md`.
- Current branch state:
  - local `dev` is ahead of `origin/dev` by 2 commits and must be pushed before the next fresh CT test.
