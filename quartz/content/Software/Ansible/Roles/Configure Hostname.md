# Configure Hostname

`ansible/roles/configure_hostname`

## Summary

Pins each node's hostname to the name it carries in the inventory, and makes sure every node can resolve every other node by name. It runs first because everything after it — the cluster, its certificates, the layout of `/etc/pve` — is keyed on the node name.

## Why it exists

The hostname was already typed into the Proxmox installer ([[installation|installation]], step 6), so on a healthy node this role changes nothing. That is precisely the point: it takes a value that was entered by hand, once, and hands ownership of it to the inventory. If a node is ever reinstalled and the name is fat-fingered, the next run catches it instead of quietly building a cluster around a typo.

The second half matters more. A Proxmox cluster talks to itself by name, not by IP address. Corosync membership, the replicated `/etc/pve` filesystem and live migration all resolve node names locally. There is no DNS in this rack yet, which means `/etc/hosts` on each node *is* the name service. Every node needs an entry for every other node, itself included, before a cluster can be formed.

## What it does

1. Sets the system hostname to the inventory name — `POD042`, `POD153`, `POD006`.
2. Writes one `/etc/hosts` line per node in the play: IP address, fully qualified name, short name. Lines are matched on the IP address, so an existing entry for that address is rewritten rather than duplicated next to it.
3. Reboots, but only if the hostname actually changed.
4. Runs `hostname` and fails the play if the answer is not the inventory name.

That last step is what keeps the role honest. Setting a value and assuming it took is how you end up debugging a cluster that half-works.

## Variables

| Variable                    | Default             | What it changes                                                 |
| --------------------------- | ------------------- | --------------------------------------------------------------- |
| `configure_hostname_domain` | `nanonode.home.lan` | The domain appended to the fully qualified name in `/etc/hosts` |

Addresses are not a role variable — they come from `ansible_host` in the inventory, falling back to the inventory hostname when a host has no address set.

## Good to know

> [!warning] This renames the OS, not a Proxmox node
> Renaming a node that is already part of a cluster is a different, much messier operation: Proxmox keeps per-node state under `/etc/pve/nodes/<name>`, and this role does not move any of it. Use it on fresh nodes, before the cluster exists — which is exactly where the playbook puts it.

> [!note] The reboot is deliberate
> Long-running services only notice a hostname change when they restart. Rebooting once here, before anything else is configured, is cheaper than hunting down services that cached the old name. Nodes that already have the right name skip the reboot entirely.

> [!note] Limited runs produce an incomplete hosts file
> The `/etc/hosts` loop covers the hosts in the current play. Running with `--limit` on a single node still refreshes what earlier full runs wrote, but a brand-new node introduced that way will not appear in the other nodes' hosts files until they are run against too.
