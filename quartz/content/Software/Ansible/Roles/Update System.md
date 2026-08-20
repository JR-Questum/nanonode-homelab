# Update System

`ansible/roles/update_system`

## Summary

A full distribution upgrade with the interactive parts defused, followed by a decision: restart the services that need it, or reboot for a new kernel.

## Why it exists

Running apt unattended on Debian has two classic traps. `needrestart` stops and asks which services should be restarted, and debconf stops and asks what to do about changed configuration files. Both wait forever when there is no terminal to answer them, so an upgrade that looked fine locally hangs the moment it is run from a playbook. Setting `NEEDRESTART_MODE=a` and `DEBIAN_FRONTEND=noninteractive` removes both prompts.

The more interesting half is what happens afterwards. Rebooting after every upgrade is wasteful, never rebooting leaves a node running an old kernel alongside freshly installed modules. `needrestart` already knows which of the two situations you are in, so the role reads its answer instead of guessing.

## What it does

1. Refreshes the apt cache.
2. Runs a `dist-upgrade` with needrestart in automatic mode and debconf silenced.
3. Cleans the package cache and removes dependencies nothing needs any more.
4. Runs `needrestart -b` for machine-readable output and pulls the kernel status out of it.
5. If the running kernel is still the right one, restarts only the services holding stale libraries.
6. If a new kernel is waiting, reboots the node.

## Variables

None. The role has no defaults file, its behaviour is fixed, and everything it decides comes from what `needrestart` reports.

## Good to know

> [!note] What the kernel status means
> The parsed `NEEDRESTART-KSTA` value is the whole decision:
>
> | Value | Meaning | Action taken |
> | --- | --- | --- |
> | `0` | Unknown | Restart services |
> | `1` | Running kernel is the expected one | Restart services |
> | `2` | Kernel ABI upgrade pending | Reboot |
> | `3` | Kernel version upgrade pending | Reboot |

> [!warning] This can be the second reboot of a single run
> Together with [[Configure Hostname]] a first run may reboot a node twice. The reboot allows ten minutes to come back, and the playbook treats any failure as fatal for every host, so a node that does not return stops the run rather than leaving a cluster half-built.
