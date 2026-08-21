# Validate Cluster Quorum

`ansible/roles/validate_cluster_quorum`

## Summary

Refuses to let a play continue unless the cluster is quorate *and* every node that should be online is online. It is used as a gate before the work starts, before each node is taken out of service, and again once it is back.

## Why it exists

A rolling update rests on one assumption: while this node is away, the others can carry its guests. Everything that makes the update safe migrating guests off, rebooting, moving them back only holds if the rest of the cluster is healthy at that exact moment.

The failure this prevents is the ugly one. Node one updates and reboots. It has not finished rejoining, but the play moves on and starts draining node two. Now two of three nodes are unavailable, the cluster loses quorum, and the shared configuration filesystem goes read-only across every node at once. A routine maintenance window has become an outage, and the play is still cheerfully working through its task list.

Checking quorum on its own is not enough, which is why the role also insists the node list is complete. A three-node cluster with one node down is still quorate, two out of three is a majority so a quorum check alone would wave the play straight through into the situation above. Demanding every expected node turns "technically still functioning" into "actually all there".

## What it does

1. Asks a node for the cluster status.
2. Retries until the cluster reports itself quorate and every expected node appears online, for up to five minutes.
3. Fails with the command's own error if the status could not be read at all.
4. Otherwise fails with a message naming exactly which nodes are missing.

## Variables

| Variable | Default | What it changes |
| --- | --- | --- |
| `validate_cluster_quorum_target` | The current host | Which node is asked for the cluster's status |
| `validate_cluster_quorum_expect_online` | Every host the play targeted | The nodes that all have to be online |
| `validate_cluster_quorum_retries` | `30` | How many times to re-ask before giving up |
| `validate_cluster_quorum_delay` | `10` | Seconds between attempts — thirty of them makes five minutes |

## Good to know

> [!note] It asks every node, not one node
> Because the target defaults to whichever host the role is running for, a play that runs it across all three nodes collects three independent opinions on the cluster's health. A disagreement, one node convinced another is offline while that node thinks it is fine, surfaces here. Asking a single node would not catch it.

> [!note] The expected list is the whole cluster, not the current batch
> The default is every host the play targeted, which is not the same as the hosts in the current pass. In a one-node-at-a-time play that distinction is the entire point: the node being updated still expects all three of them to be online.

> [!note] Reading the status is allowed to fail
> The status command is marked as never failing on its own, so the retry loop owns the outcome and the assertion afterwards decides. A node that is mid-reboot returns an error rather than an answer, and without this the play would abort on the first attempt instead of waiting for the node it just rebooted.
