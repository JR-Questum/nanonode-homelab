# Setup Host

`ansible/roles/setup_host`

## Summary

Base packages plus the `ansible` management user: the account, its SSH key and passwordless sudo. This is the role that makes every later run key-based instead of password-based.

## Why it exists

A freshly installed Proxmox node or container has exactly one account: root, with the password that was typed into the installer. The first play connects as root with that password out of the vault, because there is nothing else to connect as. That is acceptable once. It is not how the rest of the automation should work.

So this role creates the account everything else uses. By the time the second play starts, `ansible` exists on every node with the key authorised and sudo granted, and the playbook simply stops overriding the connection settings — the second play falls through to `group_vars/all.yml` and connects as `ansible` with the SSH key. The root password is used for one play in the lifetime of a node and never mentioned again.

The package lists are split three ways so the same role can serve hypervisor nodes and containers: **required** is what the automation itself depends on, **base** is what you want the moment you SSH in to debug something, and **extra** is only installed where it is asked for — `group_vars/lxc.yml` turns it on for containers and leaves the hypervisors lean.

## What it does

1. Installs the required packages: `sudo`, `python3`, `openssh-server`, `ca-certificates`, `needrestart`.
2. Installs the base tooling: `vim`, `curl`, `bind9-dnsutils`.
3. Installs the extra tooling — `git`, `jq`, `unzip`, `rsync` — only where it is enabled.
4. Creates the `ansible` group and user, with `/bin/bash`, a home directory and membership of `sudo`.
5. Authorises the management public key, without touching any other key already present.
6. Writes `/etc/sudoers.d/ansible` granting passwordless sudo, validated before it is put in place.

## Variables

| Variable                            | Default                                                               | What it changes                                                     |
| ----------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `setup_host_required_packages`      | `sudo`, `python3`, `openssh-server`, `ca-certificates`, `needrestart` | What the automation itself needs to function                        |
| `setup_host_base_packages`          | `vim`, `curl`, `bind9-dnsutils`                                       | Everyday troubleshooting tools                                      |
| `setup_host_extra_packages`         | `git`, `jq`, `unzip`, `rsync`                                         | Heavier tooling, for hosts that want it                             |
| `setup_host_install_base_packages`  | `true`                                                                | Whether to install the base list                                    |
| `setup_host_install_extra_packages` | `false`                                                               | Whether to install the extra list — enabled for containers          |
| `setup_host_user`                   | `ansible`                                                             | The management user and its group                                   |
| `setup_host_user_public_key_file`   | `~/.ssh/nanonode.pub`                                                 | Public key read from the control machine and authorised on the node |
| `setup_host_user_passwordless_sudo` | `true`                                                                | Whether to write the sudoers drop-in                                |

## Good to know

> [!note] `needrestart` is not there by accident
> [[Update System]] parses its machine-readable output to decide between restarting services and rebooting. It sits in the required list because that role has no fallback if it is missing.

> [!note] The sudoers file is validated before it is installed
> The copy task runs `visudo -cf` against the candidate file and only puts it in place if it parses. A malformed sudoers file otherwise locks sudo for every user on the node, which on a remote hypervisor is a genuinely bad afternoon.
