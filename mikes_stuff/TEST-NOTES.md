# Test Notes

## Purpose

This file captures the exact commands and expectations for testing the updated SecureClaw install flow.

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
7. Final report should show `OpenClaw: Running`.

## What Must Happen Automatically

- install Node.js and required build tools
- install `git curl wget sudo nodejs build-essential cmake make g++ python3 ca-certificates`
- install OpenClaw CLI
- install/register OpenClaw gateway service
- enable linger for target user
- install Homebrew
- install Google Chrome
- install widget/control panel and shortcuts

## What Must Not Happen Automatically

- no onboarding during setup
- no channel login during setup
- no manual API-key flow during setup

Those steps are intended to happen later by hand.

## Real CT Validation Already Completed

Validated on:

- `openclaw03`

Observed successful behavior after patched direct run:

- OpenClaw CLI installed
- `openclaw gateway install` registered user service
- gateway became active
- final report showed `OpenClaw: Running`
- onboarding was not triggered

## Commits Backing Current Test Expectations

- `e1f30a5` Harden OpenClaw installer handoff in Ubuntu setup flows
- `971a826` Allow installer shortcuts to target feature branches
- `46a86f6` Install and verify OpenClaw gateway service
