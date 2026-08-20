# Setup HA

`ansible/roles/setup_ha`

## Summary

Creates the Proxmox cluster on the primary node and joins the other two to it. Despite the name, high availability itself is not configured yet — this role builds the thing HA will eventually sit on top of.

## Why it exists

Three independent hypervisors become one system: a shared configuration filesystem, a single web interface, and guests that can move between nodes. That is the prerequisite for the high availability the [[Compute Node Module]] is aiming at, and only the prerequisite.

Done by hand it is `pvecm create` on one node and `pvecm add` on the others, with the primary's certificate fingerprint copied across by hand each time. That is fine once. It is tedious to repeat and easy to get subtly wrong when a node is reinstalled six months later — which is precisely the situation this repository exists to avoid. Here the fingerprint is read back out of the cluster's own join information instead of being pasted in.

## What it does

1. Creates the cluster on the primary node.
2. Waits until the primary reports the cluster as quorate, retrying for about a minute.
3. Fetches the join information from the primary, including the fingerprints of the nodes already in it.
4. For every other node, joins it to the cluster using the primary's fingerprint from that join information — and skips any node that is already a member.
5. Waits for each newly joined node to report itself online before moving on to the next one.

The waiting steps are what make this re-runnable. Joining a node before the previous one has finished settling fails in ways that need manual cleanup on the node, which is exactly the sort of hand-work the role is meant to remove.

## Variables

| Variable | Default | What it changes |
| --- | --- | --- |
| `setup_ha_cluster_name` | `nanonode` | The cluster name |
| `setup_ha_primary` | first host in the `proxmox` group | The node that creates the cluster; the others join it |

Credentials are read from the vault as `vault_proxmox_root_user` and `vault_proxmox_root_password` — see the gap below.

## Good to know

> [!note] Certificate validation is inconsistent
> Cluster creation verifies certificates, which is exactly what [[Proxmox API Prereqs]] makes possible. The join task disables verification. The join works either way, but it bypasses the trust store for the one task that talks to a node not yet in the cluster.

> [!note] Nodes have to be empty to join
> Proxmox refuses to add a node that already hosts guests. That is no constraint here, since the join happens on freshly installed nodes before anything is deployed, but it does mean this play is not something to point at a node that is already running workloads.
