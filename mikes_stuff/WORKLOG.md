# Worklog

## 2026-05-29

### Context

- Goal was to fix `vps-post-setup` failing on Ubuntu CTs under Proxmox VE while still stopping short of onboarding.
- User requirement: install all prerequisites plus OpenClaw itself, but do not run onboarding or channel configuration automatically.

### Root Cause Investigation

- Traced the failure path through:
  - `ubuntu/post_lockdown_setup.py`
  - `ubuntu/universal_vps_setup.py`
  - `ubuntu/local_setup.py`
  - `ubuntu/fix_openclaw.sh`
- Confirmed the repo already included a package-list change that added:
  - `git curl wget sudo nodejs build-essential cmake make g++ python3 ca-certificates`
- Confirmed that package change alone did not fix the real issue.

### First Real Failure Identified

- Reproduced the failure on real CT `openclaw03`.
- Exact failure pattern:
  - SecureClaw ran `su - openclaw -c 'curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard'`
  - OpenClaw installer said `Git not found, installing it now`
  - Then installer tried to use `sudo`
  - Then failed with `sudo: A terminal is required to authenticate`
- Conclusion:
  - Installing packages as root was not enough
  - The target user environment used by the installer still did not reliably see the tools it needed

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

### Validation of First Fix

- Confirmed Python syntax locally with:
  - Windows Python 3.14.3
  - `py_compile` on the edited setup scripts
- Directly copied patched `post_lockdown_setup.py` to `openclaw03` and ran it manually
- Result:
  - OpenClaw installed successfully
  - Homebrew installed successfully
  - Chrome installed successfully
  - Setup completed end-to-end

### Second Problem Discovered

- Even though setup completed, final report said:
  - `OpenClaw: Installed (service not active)`
- Investigation on `openclaw03` showed:
  - CLI installed correctly under `/home/openclaw/.npm-global/bin/openclaw`
  - no OpenClaw gateway user service had been registered
  - `openclaw doctor` explicitly reported:
    - `Gateway service not installed`
    - `Run openclaw gateway install when you want to install the gateway service.`

### Second Fix Implemented

- Updated the same Ubuntu setup flows plus repair script to run:
  - `openclaw gateway install`
  - as the target user
  - without onboarding
- Added helper logic to check real service state via:
  - `systemctl --user is-active openclaw-gateway`
- Updated status/reporting logic to stop checking the old nonexistent `openclaw` system service and instead check the real user service.

### Real CT Validation of Second Fix

- Ran updated `post_lockdown_setup.py` directly again on `openclaw03`
- Result:
  - OpenClaw install succeeded
  - gateway service registered
  - gateway became healthy after warm-up
  - final report showed:
    - `OpenClaw: Running`
- Onboarding was not run
- This matches desired behavior

### Branch/Deployment Flow Discovery

- Found an important testing issue in `install.sh`:
  - downloading `install.sh` from `dev` is not enough by itself
  - if `sudo bash /tmp/sc-install.sh` is run without an argument, script defaults to `main`
- Updated `install.sh` to allow normal feature-branch names instead of only `main` or `dev`
- Correct branch-sensitive testing still requires passing the branch argument explicitly unless using `main`

### Workspace/Repo Discovery

- Clarified that local layout is:
  - outer wrapper folder: `C:\Projects\SecureClaw`
  - actual repo: `C:\Projects\SecureClaw\secureclaw`
- Clarified duplicate VS Code view came from workspace file opening both:
  - `.`
  - `secureclaw`

### Commits Created This Session

- `e1f30a5` Harden OpenClaw installer handoff in Ubuntu setup flows
- `971a826` Allow installer shortcuts to target feature branches
- `46a86f6` Install and verify OpenClaw gateway service

### Current Status At End Of Session

- Active branch: `dev`
- OpenClaw install flow on real Proxmox Ubuntu CT validated when running patched code
- Setup now installs prerequisites, OpenClaw CLI, OpenClaw gateway service, Homebrew, Chrome, and desktop tooling
- Setup still stops short of onboarding, which is intentional
- Remaining next major validation:
  - test on a fresh Ubuntu CT using GitHub-hosted `dev` flow end to end
