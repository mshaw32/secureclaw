# Test Notes

## Purpose

This file captures the exact commands and expectations for testing the updated SecureClaw install flow.

## Current Test Objective

Validate the current `dev` branch on a brand new Ubuntu CT after the `openclaw05` finding:

- SecureClaw deployment should complete successfully.
- Final report should show `OpenClaw: Installed`.
- Setup should not run onboarding automatically.
- Manual `openclaw onboard` should not show the Codex plugin/module load error:
  - `openclaw/dist/plugin-sdk/root-alias.cjs/exec-approvals-runtime`

Important: local `dev` has post-test widget URL fixes and notes updates. Push `dev` before the next GitHub-hosted test command.

## Critical Branch Rule

If testing `dev`, it is not enough to download `install.sh` from the `dev` URL.

You must also pass `dev` as the argument when running the script.

Reason:
- `install.sh` chooses its branch from its argument
- if no argument is given, it defaults to `main`
- so this is wrong for `dev` testing:

```bash
wget -qO /tmp/sc-install.sh https://raw.githubusercontent.com/mshaw32/secureclaw/dev/install.sh && sudo bash /tmp/sc-install.sh
```

That command downloads the `dev` copy of `install.sh`, but then runs it with the default branch, which becomes `main`.

## Correct `dev` Test Command

Use this exact command on fresh Ubuntu CTs when testing current updated code from `dev`:

```bash
wget -qO /tmp/sc-install.sh https://raw.githubusercontent.com/mshaw32/secureclaw/dev/install.sh && sudo bash /tmp/sc-install.sh dev
```

Important:
- `dev` appears twice for a reason
- first `dev` is in the GitHub URL
- second `dev` is the argument passed to `install.sh`

Both matter.

## Correct `main` Production Command

When the fixes are merged and production-ready on `main`, expected command is:

```bash
wget -qO /tmp/sc-install.sh https://raw.githubusercontent.com/mshaw32/secureclaw/main/install.sh && sudo bash /tmp/sc-install.sh
```

That is okay on `main` because default branch is `main`.

## Expected End-To-End Flow On Fresh CT

1. Run the `install.sh` command.
2. Complete `vps-setup` first.
3. Reconnect as instructed if setup flow requires it.
4. Run `sudo vps-post-setup`.
5. At hostname prompt, pressing Enter should keep current hostname.
6. Script should complete OpenClaw install without onboarding.
7. Final report should show `OpenClaw: Installed`.
8. Log in as the target user and run `openclaw onboard`.
9. Confirm onboarding does not show the Codex plugin/module load error seen on `openclaw05`.

## What Must Happen Automatically

- install Node.js and required build tools
- install `git curl wget sudo nodejs build-essential cmake make g++ python3 ca-certificates`
- install OpenClaw CLI
- run the official OpenClaw installer using the streamed upstream-style command as the target user:
  - `curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard`
- keep explicit `PATH` and dependency checks so CT login shells can see installed tools
- enable linger for target user
- install Homebrew
- install Google Chrome
- install widget/control panel and shortcuts

## What Must Not Happen Automatically

- no onboarding during setup
- no channel login during setup
- no manual API-key flow during setup
- no OpenClaw gateway service install during setup; onboarding handles that later
- no root-downloaded `/tmp/openclaw_install.sh` wrapper for the OpenClaw installer

Those steps are intended to happen later by hand.

## Real CT Validation Already Completed

### `openclaw03` Fresh `dev` Flow Retest, 2026-05-31

- Ran GitHub-hosted `dev` flow on CT `openclaw03` at `10.0.0.101`.
- RDP user created:
  - username: `openclaw`
  - password: recorded out-of-band by user request
- Tailscale authenticated successfully.
- Tailscale IP:
  - `100.71.218.112`
- SSH over Tailscale confirmed:
  - `ssh root@100.71.218.112`
- RDP port over Tailscale confirmed:
  - `100.71.218.112:3389`
- Ran `sudo vps-post-setup` over Tailscale SSH.
- Final report showed:
  - `OpenClaw: Installed`
  - `Google Chrome 148.0.7778.215`
- OpenClaw CLI check:
  - path: `/home/openclaw/.npm-global/bin/openclaw`
  - version: `OpenClaw 2026.5.28 (e932160)`
  - Node: `v22.22.2`
  - npm: `10.9.7`
- `openclaw-gateway` was inactive before onboarding, as intended.
- Manual `openclaw onboard` reached the setup-mode prompt without the `openclaw05` Codex plugin/module load error.
- Onboarding was cancelled at setup-mode prompt to avoid completing API/channel configuration.
- Issue found during test:
  - OpenClaw Control Panel widget was fetched from `brandonbelew/secureclaw/dev`
  - runtime log showed `vps-post-setup` downloading:
    - `https://raw.githubusercontent.com/brandonbelew/secureclaw/dev/ubuntu/openclaw_widget.py`
  - hardcoded upstream references were in the widget/control-panel fetch path:
    - `ubuntu/post_lockdown_setup.py`
      - `install_openclaw_widget()` used `raw_base` pointing at `brandonbelew/secureclaw`
    - `ubuntu/local_setup.py`
      - `install_openclaw_widget()` used `raw_base` pointing at `brandonbelew/secureclaw`
    - `ubuntu/install_widget.sh`
      - standalone widget installer examples and `REPO_OWNER` pointed at `brandonbelew`
    - `ubuntu/openclaw_widget.py`
      - `REPO_OWNER` pointed at `brandonbelew`, which controlled runtime manifest/update checks
  - local `dev` has been updated so all of the above fetch widget/control-panel code from `mshaw32/secureclaw`

### `openclaw05`

- Fork `main` deployment completed successfully.
- `openclaw onboard` then failed to load Codex plugin with missing OpenClaw SDK module:
  - `openclaw/dist/plugin-sdk/root-alias.cjs/exec-approvals-runtime`
- Suspected cause:
  - our local-script `/tmp/openclaw_install.sh` installer wrapper diverged from upstream's streamed `curl | bash` installer path.
- Current `dev` test should verify the restored streamed installer path fixes this.

### `openclaw03`

Observed successful behavior after patched direct run before the gateway rollback:

- OpenClaw CLI installed
- gateway service was previously tested, but setup now intentionally leaves gateway registration to onboarding
- final report should now show `OpenClaw: Installed`
- onboarding was not triggered

## Commits Backing Current Test Expectations

- `e1f30a5` Harden OpenClaw installer handoff in Ubuntu setup flows
- `971a826` Allow installer shortcuts to target feature branches
- `46a86f6` Install and verify OpenClaw gateway service
- `2266247` Defer OpenClaw gateway setup to onboarding
- `410fc85` Restore streamed OpenClaw installer invocation
- `cee4f29` Document CT install and onboarding findings
