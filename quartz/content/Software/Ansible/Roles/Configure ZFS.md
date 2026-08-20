# Configure ZFS

`ansible/roles/configure_zfs`

## Summary

Caps the ZFS ARC so the filesystem cache does not eat the memory the guests are supposed to get. Applied both to the running kernel and to the next boot.

## Why it exists

Root on ZFS was a [[installation|deliberate choice at install time]], because it is what makes storage replication between nodes possible later. It comes with a default that does not suit a hypervisor: the ARC, ZFS's read cache, grows to roughly half of system memory. On a 24GB node that is 12GB claimed for cache before a single container starts.

ARC does give memory back under pressure, but it does so gradually, and not always fast enough for a hypervisor that wants to start a guest right now. Capping it turns "however much ZFS feels like using" into a fixed number you can subtract when planning what the node can host.

The minimum matters for the opposite reason. With only a ceiling set, ARC can be squeezed down to almost nothing when memory gets tight, and then every metadata read goes to disk on a machine that is already struggling. A 2GB floor keeps the cache useful under pressure.

## What it does

1. Checks whether the ZFS module is loaded, and skips everything if it is not, the role is harmless on a host that does not use ZFS.
2. Writes `/etc/modprobe.d/zfs.conf` with the maximum and minimum in bytes. That is the setting for the next boot.
3. Writes the maximum straight into `/sys/module/zfs/parameters/zfs_arc_max`, but only when the running value differs. That is the setting for right now.
4. Writes the minimum the same way.
5. If the modprobe file changed, rebuilds the initramfs and then refreshes the boot loader.

Step 5 is the Proxmox-specific part. With root on ZFS the boot files live on EFI partitions that `proxmox-boot-tool` keeps in sync, so a fresh initramfs has to be pushed out to them. Skip that and the setting silently fails to apply after the next reboot, which is a fantastic way to lose an hour.

## Variables

| Variable | Default | What it changes |
| --- | --- | --- |
| `configure_zfs_arc_max_gb` | `4` | Ceiling on ARC size |
| `configure_zfs_arc_min_gb` | `2` | Floor below which ARC will not be squeezed |

`vars/main.yml` converts both to bytes. Those derived values are internal, override the GB variables, not the byte ones.

## Good to know

> [!note] Two write paths, on purpose
> The modprobe file only takes effect at boot, and the `/sys` write only affects the current boot. Doing both means the node behaves the same before and after its next restart, without needing a reboot to make the change real.

> [!warning] 4GB is a starting point, not a measurement
> The figure was chosen to leave room for guests, not derived from a hit-rate. Once the nodes carry real workloads, `arc_summary` will say whether the cache is being starved or the ceiling can come down further.
