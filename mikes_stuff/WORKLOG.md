# Worklog

This file is organized newest first so future sessions can get current state quickly.

## Current State

- Active branch: `dev`
- Branch status after latest local commit:
  - `dev` has local post-test fixes/notes to push
- Latest local commits on `dev`:
  - `2266247` Defer OpenClaw gateway setup to onboarding
  - `410fc85` Restore streamed OpenClaw installer invocation
  - `cee4f29` Document CT install and onboarding findings
  - `0176702` Update notes after dev push
- Current expected fresh CT final report:
  - `OpenClaw: Installed`
- Setup currently installs prerequisites, OpenClaw CLI, Homebrew, Chrome, and desktop tooling.
- Setup intentionally does not run onboarding, channel login, manual API-key flow, or pre-onboarding gateway service installation.
- OpenClaw gateway service setup is deferred to `openclaw onboard`.
- Remaining next major validation:
  - push current `dev`
  - retest if desired to confirm widget fetches from `mshaw32/secureclaw`
  - if validation passes, merge `dev` back into fork `main` and push only to `origin`

## 2026-05-31

### Fresh Dev Flow Test On `openclaw03`

- Ran GitHub-hosted `dev` installer on CT `openclaw03` / `10.0.0.101`.
- Created RDP user `openclaw` with the requested password.
- Tailscale auth completed successfully.
- Tailscale IP assigned:
  - `100.71.218.112`
- Confirmed SSH over Tailscale:
  - `ssh root@100.71.218.112`
- Confirmed RDP port reachable over Tailscale:
  - `100.71.218.112:3389`
- Ran `sudo vps-post-setup` over Tailscale SSH.
- Final setup report showed:
  - `OpenClaw: Installed`
  - `Google Chrome 148.0.7778.215`
- OpenClaw installed via restored streamed installer path:
  - `curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard`
- Verified OpenClaw runtime:
  - `/home/openclaw/.npm-global/bin/openclaw`
  - `OpenClaw 2026.5.28 (e932160)`
  - Node `v22.22.2`
  - npm `10.9.7`
- Confirmed `openclaw-gateway` remained inactive before onboarding, as intended.
- Ran `openclaw onboard` manually as `openclaw`.
- Onboarding reached setup-mode prompt without the `openclaw05` Codex plugin/module error.
- Cancelled onboarding at setup-mode prompt to avoid completing API/channel configuration.

### Widget Source URL Issue Found

- During `vps-post-setup`, OpenClaw Control Panel downloaded from:
  - `https://raw.githubusercontent.com/brandonbelew/secureclaw/dev/ubuntu/openclaw_widget.py`
- This violated the fork test expectation that all install flow code should come from `mshaw32/secureclaw`.
- Updated local `dev` to use `mshaw32/secureclaw` for:
  - `ubuntu/post_lockdown_setup.py`
  - `ubuntu/local_setup.py`
  - `ubuntu/install_widget.sh`
  - `ubuntu/openclaw_widget.py`
- Needs push before another GitHub-hosted `dev` retest.

## 2026-05-30

### Restore Upstream-Style OpenClaw Installer Invocation

- Fresh CT `openclaw05` deployed successfully from fork `main`, but `openclaw onboard` showed:
  - `[plugins] codex failed to load`
  - `Cannot find module ...openclaw/dist/plugin-sdk/root-alias.cjs/exec-approvals-runtime`
- Since upstream did not have this onboarding failure, suspected regression is our changed installer wrapper:
  - root downloaded `https://openclaw.ai/install.sh` to `/tmp/openclaw_install.sh`
  - setup then ran that local script via `runuser -l`
- Changed setup back toward upstream behavior:
  - install CT prerequisites as root first
  - run the official streamed installer as the target user via `su -`
  - keep explicit `PATH` and dependency visibility checks for CT reliability
  - still pass `--no-onboard`
- Updated files:
  - `ubuntu/post_lockdown_setup.py`
  - `ubuntu/universal_vps_setup.py`
  - `ubuntu/local_setup.py`
  - `ubuntu/fix_openclaw.sh`
- Needs validation on a brand new CT from GitHub-hosted `dev`.
- Commit created:
  - `410fc85` Restore streamed OpenClaw installer invocation

### Gateway Install Rollback

- Removed the setup-time `openclaw gateway install` call from:
  - `ubuntu/post_lockdown_setup.py`
  - `ubuntu/universal_vps_setup.py`
  - `ubuntu/local_setup.py`
  - `ubuntu/fix_openclaw.sh`
- Reason:
  - OpenClaw installs/registers the gateway service during `openclaw onboard`
  - upstream is unlikely to accept pre-onboarding gateway service installation
- Updated final reports and security checks to verify OpenClaw CLI installation instead of expecting `openclaw-gateway` to be active.
- Onboarding remains manual and should later create the gateway service.
- Commit created:
  - `2266247` Defer OpenClaw gateway setup to onboarding

## 2026-05-29

### End Of Session Status

- Active branch: `dev`
- OpenClaw install flow on real Proxmox Ubuntu CT validated when running patched code.
- Superseded on 2026-05-30:
  - setup no longer installs/registers the OpenClaw gateway service before onboarding
- At that point, setup installed prerequisites, OpenClaw CLI, OpenClaw gateway service, Homebrew, Chrome, and desktop tooling.
- Setup still stopped short of onboarding, which was intentional.
- Remaining next major validation:
  - test on a fresh Ubuntu CT using GitHub-hosted `dev` flow end to end

### Commits Created This Session

- `e1f30a5` Harden OpenClaw installer handoff in Ubuntu setup flows
- `971a826` Allow installer shortcuts to target feature branches
- `46a86f6` Install and verify OpenClaw gateway service

### Workspace/Repo Discovery

- Clarified that local layout is:
  - outer wrapper folder: `C:\Projects\SecureClaw`
  - actual repo: `C:\Projects\SecureClaw\secureclaw`
- Clarified duplicate VS Code view came from workspace file opening both:
  - `.`
  - `secureclaw`

### Branch/Deployment Flow Discovery

- Found an important testing issue in `install.sh`:
  - downloading `install.sh` from `dev` is not enough by itself
  - if `sudo bash /tmp/sc-install.sh` is run without an argument, script defaults to `main`
- Updated `install.sh` to allow normal feature-branch names instead of only `main` or `dev`.
- Correct branch-sensitive testing still requires passing the branch argument explicitly unless using `main`.

### Real CT Validation of Second Fix

- Ran updated `post_lockdown_setup.py` directly again on `openclaw03`.
- Result:
  - OpenClaw install succeeded
  - gateway service registered
  - gateway became healthy after warm-up
  - final report showed:
    - `OpenClaw: Running`
- Onboarding was not run.
- This matched the desired behavior at the time, but was superseded on 2026-05-30 because gateway registration belongs to `openclaw onboard`.

### Second Fix Implemented

- Updated the same Ubuntu setup flows plus repair script to run:
  - `openclaw gateway install`
  - as the target user
  - without onboarding
- Added helper logic to check real service state via:
  - `systemctl --user is-active openclaw-gateway`
- Updated status/reporting logic to stop checking the old nonexistent `openclaw` system service and instead check the real user service.
- Superseded on 2026-05-30.

### Second Problem Discovered

- Even though setup completed, final report said:
  - `OpenClaw: Installed (service not active)`
- Investigation on `openclaw03` showed:
  - CLI installed correctly under `/home/openclaw/.npm-global/bin/openclaw`
  - no OpenClaw gateway user service had been registered
  - `openclaw doctor` explicitly reported:
    - `Gateway service not installed`
    - `Run openclaw gateway install when you want to install the gateway service.`

### Validation of First Fix

- Confirmed Python syntax locally with:
  - Windows Python 3.14.3
  - `py_compile` on the edited setup scripts
- Directly copied patched `post_lockdown_setup.py` to `openclaw03` and ran it manually.
- Result:
  - OpenClaw installed successfully
  - Homebrew installed successfully
  - Chrome installed successfully
  - Setup completed end-to-end

### First Fix Implemented

- Reworked OpenClaw install flow in:
  - `ubuntu/post_lockdown_setup.py`
  - `ubuntu/universal_vps_setup.py`
  - `ubuntu/local_setup.py`
  - `ubuntu/fix_openclaw.sh`
- New approach:
  - install dependencies as root
  - download OpenClaw installer to `/tmp/openclaw_install.sh`
  - run installer as target user via `runuser -l` when available, otherwise `su -`
  - set explicit PATH
  - verify `git curl sudo node npm bash` are visible before invoking installer

### First Real Failure Identified

- Reproduced the failure on real CT `openclaw03`.
- Exact failure pattern:
  - SecureClaw ran `su - openclaw -c 'curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard'`
  - OpenClaw installer said `Git not found, installing it now`
  - Then installer tried to use `sudo`
  - Then failed with `sudo: A terminal is required to authenticate`
- Conclusion:
  - Installing packages as root was not enough
  - the target user environment used by the installer still did not reliably see the tools it needed

### Root Cause Investigation

- Traced the failure path through:
  - `ubuntu/post_lockdown_setup.py`
  - `ubuntu/universal_vps_setup.py`
  - `ubuntu/local_setup.py`
  - `ubuntu/fix_openclaw.sh`
- Confirmed the repo already included a package-list change that added:
  - `git curl wget sudo nodejs build-essential cmake make g++ python3 ca-certificates`
- Confirmed that package change alone did not fix the real issue.

### Context

- Goal was to fix `vps-post-setup` failing on Ubuntu CTs under Proxmox VE while still stopping short of onboarding.
- User requirement: install all prerequisites plus OpenClaw itself, but do not run onboarding or channel configuration automatically.
