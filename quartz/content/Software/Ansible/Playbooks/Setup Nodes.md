# Setup Nodes

`ansible/playbooks/setup_nodes.yml`

## Summary

One playbook takes three freshly installed Proxmox nodes and leaves a working cluster behind. It is split into two plays that connect as two different users, and that split is the whole idea.

## Play 1 — Commission the nodes

Connects as **root, with the password from the vault**, because that is the only account a fresh [[installation|Proxmox install]] has. Eight roles run in a fixed order:

| Role                        | What it gets you                                                     |
| --------------------------- | -------------------------------------------------------------------- |
| [[Configure Hostname]]      | The node knows its name, and every node knows the others             |
| [[Configure Chrony]]        | All three clocks agree before anything is clustered                  |
| [[Configure Proxmox Repos]] | apt works without a subscription key                                 |
| [[Configure Proxmox Hosts]] | Microcode, a CPU governor that survives reboots, a VLAN-aware bridge |
| [[Setup Host]]              | Packages, the `ansible` user, its key and sudo                       |
| [[Configure ZFS]]           | The filesystem cache stops competing with the guests                 |
| [[Update System]]           | Fully upgraded, then restarted or rebooted as needed                 |
| [[Remove Subscription Nag]] | No popup at every login                                              |

The order is not alphabetical and not arbitrary — each role clears a blocker for the ones after it. Repositories are fixed before anything installs a package. `needrestart` is installed before the role that parses its output. The subscription patch comes after the upgrade that would otherwise undo it.

## Play 2 — Create the cluster

The second play sets no connection variables at all, and that is the payoff. Play 1 created the `ansible` user, authorised the key and granted sudo, so play 2 falls through to `group_vars/all.yml` and connects as that user with the SSH key. The root password is used for exactly one play in the lifetime of a node.

| Role | What it gets you |
| --- | --- |
| [[Proxmox API Prereqs]] | API libraries on every node, and the cluster CA trusted |
| [[Setup HA]] | The cluster created and both other nodes joined |

## Running it

```bash
ansible-playbook playbooks/setup_nodes.yml
```

On a control machine that has never run this before, first install the collections it depends on:

```bash
ansible-galaxy collection install -r requirements.yml
```

It also expects a real inventory in `private/` (start by copying `private.example/`), the vault password at `~/.config/nanonode/vault_pass`, and the management SSH key at `~/.ssh/nanonode`. See [[Ansible overview]] for the full setup.

## Why it is shaped this way

### Facts are never gathered

Both plays skip fact gathering. None of the roles need it — they work from inventory values, and where they need to know something about the machine they check it directly: does this CPU expose frequency scaling, is the ZFS module loaded, is this node already in the cluster. Asking the host directly is more honest than a general-purpose fact dump, and it saves a full round trip per node at the start of each play. The trade is that a future role wanting facts has to ask for them explicitly.

### Any error is fatal

If one node fails, the run stops for all of them. For a cluster, half-configured is worse than not configured: two nodes in a cluster and one left behind is a worse place to debug from than three plain nodes.

### One step at a time

The nodes move through the playbook in lockstep rather than racing ahead independently. It is slower, but reboots and cluster joins are far easier to reason about — and to read in the output — when all three nodes are on the same task.

## Not there yet

- High availability itself: no replication jobs, no HA groups, no shutdown policy. See the gaps flagged on [[Setup HA]].
- No guests. The playbook builds the platform; nothing is deployed onto it yet.
- The example inventory currently only describes the Proxmox hosts. `group_vars/lxc.yml` is still there, waiting for container hosts to come back into the inventory.
