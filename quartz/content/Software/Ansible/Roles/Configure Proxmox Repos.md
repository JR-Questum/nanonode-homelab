# Configure Proxmox Repos

`ansible/roles/configure_proxmox_repos`

## Summary

Moves the node off the enterprise apt repositories, which need a paid subscription, and onto the no-subscription repository so that updates work at all.

## Why it exists

A fresh Proxmox install points at `enterprise.proxmox.com`. Without a subscription key, every `apt update` ends in `401 Unauthorized`. That is not a cosmetic problem: [[Setup Host]] installs packages and [[Update System]] runs a full dist-upgrade, and neither can do anything until apt is healthy. So this role runs before both of them.

The no-subscription repository ships the same packages with less testing behind them. For a homelab that trade is fine. Under a support contract it would not be, and the role is written so that flipping back is a one-line change rather than a rebuild.

## What it does

1. Disables the `pve-enterprise` repository.
2. Disables the enterprise `ceph` repository. Ceph is not used here — storage replication is done with ZFS — but the entry still breaks `apt update` while it points at a subscription-only host.
3. Enables the `pve-no-subscription` repository.

All three are written as deb822 `.sources` files, which is the format Proxmox 9 and Debian 13 ship. The entry names match the files Proxmox writes itself, so these are rewritten in place instead of leaving a disabled copy sitting next to an enabled original.

## Variables

| Variable | Default | What it changes |
| --- | --- | --- |
| `configure_proxmox_repos_suite` | `trixie` | The Debian release the repositories track — Proxmox VE 9 is built on Debian 13 |
| `configure_proxmox_repos_keyring` | `/usr/share/keyrings/proxmox-archive-keyring.gpg` | The key used to verify the repositories |
| `configure_proxmox_repos_ceph_release` | `ceph-squid` | Which Ceph release line the disabled entry refers to |

## Good to know

> [!note] Entries are disabled, not deleted
> The enterprise repositories stay on disk with `Enabled: no`. If a subscription is ever bought, turning them back on is a flag, not a rediscovery of the correct URLs and components.

> [!warning] The suite is pinned by hand
> Nothing derives `trixie` from the running release. A major Proxmox or Debian upgrade means editing this default, otherwise the role keeps confidently writing repository entries for the previous release.
