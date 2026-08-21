# Update Cluster

`ansible/playbooks/update_cluster.yml`

## Summary

Updates a cluster that is already carrying workloads: one node at a time, guests moved out of the way first, and the cluster's health checked before, between and after.

## Why it is a separate playbook

[[Setup Nodes]] updates nodes too, but it does it on hardware nobody is using yet. Three fresh installs that can reboot whenever they like. Once the cluster is real and carrying guests, the same job needs completely different rules: 
	nodes go down one at a time, never while the cluster is already short a member, and never while something is still running on them.

Those rules are what this playbook is. The actual updating is still [[Update System]], doing what it did during commissioning. Everything around it is new.

## The three plays

### Pre-flight

Every node is asked whether the cluster is quorate and complete, and all of them have to agree before anything is touched. Starting a rolling update on a cluster that is already one node down is how a maintenance window turns into an outage.

### The rolling update

Runs one node at a time. For each node in turn:

1. **Does it need anything?**  [[Check Pending Updates]] looks for pending packages or a kernel that has been installed but never booted. A node with nothing to do skips everything below.
2. **Is the cluster still healthy?**  [[Validate Cluster Quorum]] again, per node, immediately before it is taken out of service. The answer from five minutes ago is not good enough when the thing that changed in between was another node rebooting.
3. **Drain it**  [[Ensure HA Maintenance]] moves the HA guests to the other nodes and waits until none are left.
4. **Update it**  [[Update System]] upgrades and, if a new kernel is waiting, reboots.
5. **Is it back?**  quorum and the full node list again, this time waiting for the node that just rebooted to rejoin.
6. **Return it to service**  maintenance mode off, guests can be placed on it again.

Then the next node.

The subscription patch runs on every node regardless of whether it needed updating. It costs nothing when there is nothing to patch, and it re-applies the change on any node whose web toolkit was just replaced.

### Post-flight

The same health check as the pre-flight, once everything is done. Quorum from every node's point of view, every node online, nothing left half-drained.

## Running it

```bash
ansible-playbook playbooks/update_cluster.yml
```

## Good to know

> [!note] The first failure stops everything
> One node at a time, with any failure fatal for the whole run, means a problem on the second node leaves the third untouched. That is the right default — a cluster that has just failed to update a node should not immediately start on the next one — but note the consequence flagged on [[Ensure HA Maintenance]]: the node that failed stays drained until it is put back by hand.

> [!note] Worst-case timing
> Every wait in the run is thirty attempts, ten seconds apart. A single node can in theory spend five minutes waiting for quorum, five for its guests to drain and five more rejoining after the reboot. Unattended that is fine; it is worth knowing before watching a run and assuming it has hung.

> [!note] Built slightly ahead of the workload
> The drain was verified with a test container restored from backup, it moved off the node and came back so the mechanism is proven. The cluster does not carry guests of its own yet, so for now the playbook is mostly doing the other half of the job: one node at a time, health checked at every step, with very little actually to move.
