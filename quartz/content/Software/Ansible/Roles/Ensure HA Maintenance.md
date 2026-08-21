# Ensure HA Maintenance

`ansible/roles/ensure_ha_maintenance`

## Summary

Puts a node into HA maintenance mode so the cluster moves its guests elsewhere, and takes it back out again afterwards. 

## Why it exists

This is the part that turns "reboot the node" into "reboot the node without anyone noticing".

Maintenance mode tells the cluster manager that a node should not be running anything. Guests under HA management migrate away, and nothing new is placed there until the node comes out of maintenance. Crucially it uses live migration, so a guest keeps running on another node while this one reboots. The alternative, stopping and starting it, is visible to whatever that guest was serving.

The role covers both directions because they are the same operation with a different argument, and because it makes the playbook read honestly: drain before, restore after, the same role named twice with opposite intent.

## What it does

1. Rejects any state that is not `enabled` or `disabled` before doing anything.
2. Reads the HA manager's view of the cluster and works out whether the node is already in the requested state.
3. Issues the maintenance command only if it is not. Running it twice is harmless, but it would report a change that did not happen.
4. Waits for the HA manager to confirm the new state. When draining, it waits further, until no HA services are assigned to the node at all.

Step 4 is the whole value of the role. The command returns the moment it is accepted, long before the migrations it triggers have finished. Without the wait, the play would start rebooting a node while its guests were still being moved off it.
## Variables

| Variable | Default | What it changes |
| --- | --- | --- |
| `ensure_ha_maintenance_node` | The current host | The node being put into or taken out of maintenance |
| `ensure_ha_maintenance_state` | `disabled` | `enabled` drains the node, `disabled` returns it to service |
| `ensure_ha_maintenance_target` | The current host | The node asked to carry out the command |
| `ensure_ha_maintenance_retries` | `30` | Attempts while waiting for the state to settle |
| `ensure_ha_maintenance_delay` | `10` | Seconds between attempts — five minutes in total |

The node and the target are separate on purpose. Maintenance mode is a cluster-level instruction, so any member can issue it, which leaves room to drain a node that is no longer answering for itself.

## Good to know

> [!note] `disabled` is the default for a reason
> Called with no state at all, the role returns a node to normal service. The direction that takes a node out of service has to be asked for explicitly.

> [!note] It stands aside when there is no HA to talk to
> Before issuing anything, the role checks that the HA manager answered and that it knows about this node. If either is untrue it does nothing and the play continues. The node is updated and rebooted without a drain, which on a cluster not running HA is exactly right. Worth knowing which of the two happened, though, because a skipped drain looks identical in the output to a drain that had nothing to move.

> [!warning] A failed run leaves the node drained
> If something fails after the drain, the play stops and the node stays in maintenance mode. Nothing will be placed on it until it is put back by hand:
> ```bash
> ha-manager crm-command node-maintenance disable <node>
> ```

