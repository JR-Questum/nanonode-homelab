# Remove Subscription Nag

`ansible/roles/remove_subscription_nag`

## Summary

Patches the "No valid subscription" popup out of the Proxmox web interface, then restarts the web proxy so the patched file is actually served.

## Why it exists

Purely cosmetic, and it is worth being clear that this is all it is. Running on the no-subscription repository means the dialog appears at every login to every node. Three nodes, three dismissals, every time. The role changes nothing about licensing, about which repositories are configured, or about what Proxmox will and will not do.

## What it does

1. Rewrites the call that shows the dialog in `proxmoxlib.js` so it is commented out at its head and never runs.
2. Restarts `pveproxy`, but only when the file actually changed — the browser is served a cached copy of that JavaScript otherwise.

The pattern used to find the dialog explicitly refuses to match text it has already patched, so a second run finds nothing to do. The role is idempotent without having to track whether it ran before.

## Variables

None.

## Good to know

> [!note] Every upgrade undoes it
> The file belongs to `proxmox-widget-toolkit`, so any package upgrade restores the original. That is exactly why this is the last role in the play, right after [[Update System]], instead of a one-off manual edit that quietly stops being true.

> [!warning] It edits a vendor file with a pattern match
> If Proxmox restructures that dialog upstream, the pattern stops matching. It fails softly: the task reports no change and the popup comes back. Nothing breaks, but nothing warns either, the only symptom is the dialog reappearing.
