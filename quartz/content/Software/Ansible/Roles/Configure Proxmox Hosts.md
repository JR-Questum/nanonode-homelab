# Configure Proxmox Hosts

`ansible/roles/configure_proxmox_hosts`

## Summary

The hardware-facing role: CPU microcode, a frequency governor that survives reboots, and VLAN awareness on the management bridge.

## Why it exists

Two goals from the [[Compute Node Module]] end up here predictable power draw, and a network that can carry tagged traffic to guests.

Power first. The [[Bios Settings|BIOS settings]] already disable turbo; the governor is the operating system half of the same decision. All three nodes hang off a single [[Power Delivery Module]] over USB-C PD, so a flat, predictable draw is worth more than the last few percent of burst performance. `powersave` keeps the cores near their minimum ratio until there is real demand.

The catch is that governor settings do not survive a reboot. `/sys` is not persistent and Debian ships no unit to reapply it, so the role writes the choice to `/etc/default/cpupower` and installs a small oneshot service that applies it at every boot.

Networking second. The Proxmox installer creates `vmbr0` as a plain bridge that only passes untagged traffic. Making it VLAN-aware means a guest can be dropped onto a tagged VLAN by setting a tag on its virtual NIC, instead of building a separate bridge per VLAN and rewiring the host every time a network is added.

## What it does

1. Installs `intel-microcode`.
2. Checks whether `/sys/devices/system/cpu/cpu0/cpufreq` exists. If it does not — a virtualised test host, or SpeedStep switched off in the BIOS — it prints why and skips the entire governor block, which keeps the role usable on a throwaway VM.
3. Installs `linux-cpupower`, reads the governors the CPU driver actually supports and asserts the requested one is among them. A wrong value fails the play with the list of valid ones, rather than writing a setting the driver silently ignores.
4. Writes `GOVERNOR=` to `/etc/default/cpupower`, deploys a `cpupower.service` oneshot unit that reads it, and applies the governor immediately if the running one differs.
5. Adds `bridge-vlan-aware yes` and `bridge-vids 2-4094` to the `vmbr0` stanza in `/etc/network/interfaces`, inside a marked block, and reloads the network configuration with `ifreload -a`.

## Variables

| Variable                       | Default     | What it changes                                                        |
| ------------------------------ | ----------- | ---------------------------------------------------------------------- |
| `configure_cpu_governor_mode`  | `powersave` | The CPU frequency governor, validated against what the driver supports |
| `setup_host_install_microcode` | `true`      | To decide whether to install microcode                                 |

## Good to know

> [!note] Reloading the bridge you are connected over
> `ifreload -a` re-applies `/etc/network/interfaces` on the live host, including the bridge carrying the SSH session that is running the play. In practice ifupdown2 only reconfigures what changed and the session survives, but this is the one task in the run capable of cutting its own connection. It is a handler, so it fires once at the end of the role rather than in the middle of it.

> [!note] The block edit assumes the stock layout
> The VLAN lines are inserted after the first line matching `iface vmbr0 inet`, which is what the installer produces. A hand-edited or renamed bridge means they land somewhere else, or nowhere.
