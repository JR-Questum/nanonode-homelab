# Check Pending Updates

`ansible/roles/check_pending_updates`

## Summary

Works out whether a node actually needs anything, packages waiting to install, or a kernel installed but not yet running and records the answer so the rest of the play can skip nodes that are already current.

## Why it exists

Updating a node in a live cluster is expensive. It gets drained of guests, upgraded, rebooted and brought back, and every guest on it migrates twice. Several minutes per node, and a handful of moving parts that each have to work. Doing all of that on a node with nothing to install is pure risk, because every migration and every reboot is another chance for something not to come back.

So the play asks first. Two things count as "needs something", and the second one is why this role is more than a package count. Packages waiting to be installed is the obvious case. The other is a kernel that has been installed but never booted into: apt considers that node perfectly up to date while it carries on running the old kernel. A node that was upgraded but never rebooted would otherwise be skipped forever by the one playbook designed to reboot it.

## What it does

1. Refreshes the apt cache, explicitly reporting no change, nothing here modifies the node.
2. Asks apt what a `dist-upgrade` *would* do, without doing it.
3. Counts the packages that answer names as installs.
4. Finds the newest kernel present in `/boot` and compares it against the one currently running.
5. Sets the verdict: anything to install, or a newer kernel sitting unused, means the node needs a pass.
6. Prints a one-line summary, package count, running kernel, newest installed kernel, and the decision.

## Variables

None, the role has no defaults file and nothing about it is tunable. It produces facts rather than consuming variables:

| Fact                                   | What it holds                                            |
| -------------------------------------- | -------------------------------------------------------- |
| `check_pending_updates_count`          | How many packages a dist-upgrade would install           |
| `check_pending_updates_kernel_pending` | Whether a newer kernel is installed than the one running |
| `check_pending_updates_required`       | The verdict [[Update Cluster]] keys off                  |

## Good to know

> [!note] Every task here is read-only, deliberately
> Each one is marked as making no change and as safe to run during a dry run. A `--check` run therefore still produces a real verdict, instead of skipping the detection and leaving the rest of the play working from an undefined variable.

> [!note] It answers for one node, about one node
> The role makes no cluster-wide judgement, it inspects the host it runs on and says whether that host needs a pass. Deciding whether the *cluster* is in a fit state to do anything about it belongs to [[Validate Cluster Quorum]].
