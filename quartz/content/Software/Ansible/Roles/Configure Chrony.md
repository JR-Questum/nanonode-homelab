# Configure Chrony

`ansible/roles/configure_chrony`

## Summary

Replaces Debian's default time setup with chrony pointed at the Belgian NTP pool, and refuses to hand back control until the clock has actually converged.

## Why it exists

A Proxmox cluster is unusually sensitive to time. Corosync uses timestamps to work out who is still alive, and HA fencing decides whether to power-cycle a node based on how long it has been silent. Two nodes that disagree about what second it is can make that decision for the wrong reasons. Certificates, backup windows and replication timestamps all quietly depend on the same thing.

The hardware clock on each node is [[Bios Settings|kept in UTC]] and Proxmox applies the timezone on top of that, so the only job left is keeping that UTC clock disciplined against an upstream source.

These nodes can also be wrong by a lot rather than a little. They share a [[Power Delivery Module]] and are expected to come back on their own after an outage, sometimes after sitting unpowered for a while. A time daemon that only slews — nudging the clock a few parts per million at a time — would take hours to walk back a large offset. That is what `makestep` is for.

## What it does

1. Installs chrony.
2. Writes `/etc/chrony/chrony.conf` from a template: the pool servers with `iburst`, plus `rtcsync` so corrected time is pushed back to the hardware clock, `leapsectz right/UTC`, a drift file and a log directory.
3. Restarts chrony when the config changed, then makes sure it is enabled and running either way.
4. When the config changed, forces an immediate correction with `chronyc -a makestep` and then blocks on `chronyc waitsync` until the clock reports itself synchronised.

Step 4 is why a first run can sit here for a moment. The role is deliberately waiting for the clock rather than assuming it caught up.

## Variables

| Variable                       | Default                                   | What it changes                                                                                                                |
| ------------------------------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `configure_chrony_ntp_servers` | `0.be.pool.ntp.org` … `3.be.pool.ntp.org` | Upstream time sources                                                                                                          |
| `configure_chrony_makestep`    | `"1.0 3"`                                 | Step the clock instead of slewing it when the offset is over 1 second, but only during the first 3 updates after chrony starts |

## Good to know

> [!note] Runs before the cluster exists
> This is the second role in the run, right after hostnames, so all three nodes agree on the time before any of them try to form a cluster. Fixing time drift afterwards means arguing with a cluster that is already using those timestamps to make decisions.
