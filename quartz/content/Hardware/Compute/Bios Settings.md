# BIOS Settings for Compute Nodes

## Summary

Proper BIOS configuration is a foundational step in building reliable, efficient, and observable compute nodes for a homelab environment.

Out-of-the-box BIOS settings on repurposed hardware are typically tuned for general-purpose desktop use, not for headless server workloads. Adjusting these settings ensures faster boot times, lower idle power consumption, better compatibility with hypervisors like Proxmox, and more predictable behavior in high-availability cluster scenarios.

The [[Compute Node Module|nodes]] came with outdated bios versions and preinstalled with windows 11, i took advantage of that in order to update the bios via the bios update tool provided by Lenovo. 

## Goals

The BIOS configuration is designed around the following homelab-specific goals:

- minimize boot time for faster reboots and HA failovers
- reduce idle power consumption across the cluster
- ensure automatic recovery after power outages
- maximize compatibility with Linux hypervisors and virtualization features
- free system resources (RAM, PCIe lanes, interrupts) for guest workloads

## Design Principles

### Headless-first configuration

Compute nodes in a homelab rack are managed remotely. BIOS settings should reflect this by disabling features that consume resources but provide no value in a headless context, such as audio, excessive video memory, and legacy boot support.

### Power efficiency without sacrificing performance

Power-saving features should be enabled where they do not interfere with workload performance. Modern processors benefit from racing to sleep — boosting quickly to finish tasks and returning to deep idle states — rather than running at reduced clocks for extended periods.

### Automatic recovery

A homelab cluster should be able to heal itself after common failure scenarios. BIOS settings must ensure nodes power on automatically after an outage, boot without user intervention, and do not hang waiting for passwords or legacy boot media.

### Hypervisor compatibility

Settings should prioritize clean operation under Proxmox and KVM. This means disabling enterprise security features that can conflict with hypervisors, enabling virtualization extensions, and avoiding configurations that complicate PCIe passthrough or custom kernel modules.

## Configuration Reference

These are the settings that are set on each [[Compute Node Module|Node]]

### Main

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| System Time & Date | UTC | Proxmox requires UTC on the hardware clock and handles time zones internally. Syncing all nodes to UTC prevents time-drift across the cluster. |

### Devices

#### USB Setup

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| USB Support | Enabled | USB access is still needed for emergency physical keyboard access during troubleshooting. |
| USB Legacy Support | Enabled | Maintains compatibility with older bootable USB rescue drives. |
| USB Enumeration Delay | Disabled | Speeds up the boot process by removing an unnecessary pause. |
| Front USB Ports | Enabled | Disabling these saves negligible power when unused; keeping them active aids troubleshooting. |
| Rear USB Ports | Enabled | Same reasoning as front ports. |

#### ATA Drive Setup

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| SATA Controller | Enabled | Required for drive connectivity. |
| Configure SATA as | AHCI | Absolute necessity. Proxmox and ZFS require direct access to drives. Never use IDE or RAID modes. |
| Hard Disk Pre-Delay | Disabled | Solid-state drives do not require spin-up time. Disabling this reduces boot time. |

#### Video Setup

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| Select Active Video | IGD (Integrated Graphics) | Integrated graphics is sufficient for headless operation. |
| Pre-Allocated Memory Size | Minimum / 32 MB | Proxmox is headless and does not need video memory. Lowering this frees system RAM for virtual machines. |
| Total Graphics Memory | Minimum / 128 MB | Same reasoning as pre-allocated memory. |

#### Audio Setup

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| Onboard Audio Controller | Disabled | A Proxmox server does not need audio. Disabling the chip saves a small amount of power and frees PCI lanes and interrupts. |

#### Network Setup

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| Onboard Ethernet Controller | Enabled | Essential for network connectivity. |
| PXE Option ROM | Disabled | Booting from internal SSDs, not network. Disabling this removes a step in the boot sequence for faster reboots during HA failovers. |
| PXE IPv4 Network Stack | Disabled | Network boot is not required. |
| PXE IPv6 Network Stack | Disabled | Network boot is not required. |
| TFTP Window Size | Default | Dormant when PXE is disabled; no impact on boot speed or power consumption. |

#### PCI Express Configuration

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| ASPM Support | Auto | Active State Power Management allows PCIe links to drop into low-power sleep states when idle, significantly reducing wall-power draw. |
| PCIe 8x Slot Speed | Auto | The motherboard will negotiate correctly with add-in cards such as 10GbE or quad-port NICs. |

### Advanced

#### CPU Setup

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| EIST Support | Enabled | Enhanced Intel SpeedStep allows the CPU to dynamically adjust voltage and core frequency based on load. |
| Core Multi-Processing | Enabled | Allows use of all physical and logical cores. |
| Intel Virtualization Technology (VT-x) | Enabled | Mandatory for Proxmox to run KVM virtual machines efficiently. |
| VT-d | Enabled | Required for hardware passthrough to VMs — e.g., passing a Coral TPU, GPU, or PCIe network card directly to a guest OS. |
| TxT | Disabled | Trusted Execution Technology is an enterprise feature unnecessary for homelabs and can occasionally cause hypervisor conflicts. |
| C1E Support | Enabled | Allows the CPU to halt and save power when idle. |
| C State Support | C1C3C6C7C8C10 (full range) | Crucial for achieving low idle power figures (5W–10W) on compact Lenovo nodes. |
| Turbo Mode | Enabled | Processors are designed to race to sleep. Boosting to finish tasks quickly and returning to idle C-states is more power-efficient than sustained base-clock operation. |

#### Intel Software Guard Extensions (SGX)

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| Intel SGX Control | Disabled | SGX is largely deprecated for homelab VMs. Disabling it removes memory overhead and a potential security vulnerability. |

#### Other Advanced Settings

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| Intel SIPP Support | Disabled | Corporate deployment feature; irrelevant for Proxmox. |
| Dust Shield Alert | Disabled | Unnecessary for a homelab environment. |

### Power

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| After Power Loss | Power On | Critical for HA clusters. Nodes must turn themselves back on automatically when power returns so the cluster can heal. |
| Enhanced Power Saving Mode | Enabled | Reduces power draw when the system is shut down but still plugged in. |
| Smart Power On | Disabled | Keyboard-based boot is unnecessary for a server. |
| ICE Performance Mode | Better Acoustic Performance | Lenovo nodes run cool naturally. Acoustic mode keeps fans at minimum RPMs, saving power and maintaining silence. Fans will still ramp up if temperatures become dangerous. |
| ICE Thermal Alert | Enabled | Provides a safeguard against thermal issues. |
| Wake Up on Alarm | Disabled | Let Proxmox handle HA and uptime; BIOS-level alarms are not required. |

### Security

| Setting                                 | Recommended Value | Rationale                                                                                                                              |
| --------------------------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Administrator Password                  | None              | Use for BIOS access control.                                                                                                           |
| Power-On Password                       | None              | A power-on password will cause the server to hang at the BIOS screen after a power outage, breaking HA recovery.                       |
| Hard Disk Password                      | None              | Same risk as power-on password — prevents automatic boot after power loss.                                                             |
| Allow Flashing BIOS to Previous Version | Enabled           | If a future BIOS update breaks Proxmox, the ability to downgrade is valuable.                                                          |
| Windows UEFI Firmware Update            | Disabled          | Running Linux/Proxmox, not Windows.                                                                                                    |
| Smart USB Protection                    | Disabled          | Prevents the BIOS from blocking bootable USB drives needed for Memtest or Proxmox reinstallation.                                      |
| Security Chip 2.0 (TPM)                 | Enabled           | Proxmox can ignore it, but having it active enables vTPM passthrough for Windows 11 VMs.                                               |
| Secure Boot                             | Disabled          | While Proxmox can work with Secure Boot, disabling it prevents issues with unsigned drivers, custom ZFS modules, and PCIe passthrough. |
| Device Guard                            | Disabled          | Enterprise feature not needed for homelab use.                                                                                         |
| Chassis Intrusion Detection             | Disabled          | Not applicable in a homelab environment.                                                                                               |
| Configuration Change Detector           | Disabled          | Not required for homelab operation.                                                                                                    |

### Startup

| Setting | Recommended Value | Rationale |
|---------|-------------------|-----------|
| CSM (Compatibility Support Module) | Disabled | Forces pure UEFI boot. Proxmox installs cleanly in UEFI mode. This speeds up boot times and removes legacy BIOS overhead. |
| Boot Up Num-Lock Status | Off | Irrelevant for a headless server. |

## Benefits

Applying these BIOS settings is expected to provide the following practical benefits:

- faster boot times and shorter HA failover windows
- lower idle power consumption across the cluster
- automatic recovery after power outages without manual intervention
- better resource availability for guest virtual machines
- fewer compatibility issues with Proxmox, ZFS, and PCIe passthrough
- more predictable and consistent behavior across all compute nodes