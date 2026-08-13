# Proxmox Installation

## Summary

This page documents the base Proxmox VE installation as performed on each [[Compute Node Module|compute node]]. The installation is deliberately kept identical across all three nodes so that cluster and high availability configuration can be applied afterwards without per-node exceptions.

> [!note] Version
> This guide was written against **Proxmox VE 9.2-1**. Screens may differ slightly on other releases.

## Before Starting

- The [[Bios Settings|BIOS settings]] should be applied before installing, in particular AHCI mode, UEFI boot with CSM disabled, and the virtualization extensions.
- The installer is written to a USB drive and booted on the node.
- Installation is performed per node, with only the hostname and network details differing between them.

> [!info] About the screenshots
> This guide was captured on a virtual machine, so the disk shows as 32GB. The physical nodes use their full 512GB of local storage.

## Installation Steps

### 1. Select the graphical installer

Boot from the installer media and choose the graphical user interface option.

![[Installation_1.jpg]]

### 2. Accept the EULA

![[Installation_2.jpg]]

### 3. Configure the target disk as ZFS

The target disk is set up as **ZFS**, which is what makes high availability possible later on. ZFS is a hard requirement for the replication and HA behaviour planned for this cluster, so this choice cannot be deferred to a later stage without reinstalling.

![[Installation_3.jpg]]

### 4. Set location, timezone and keyboard layout

Fill in the country, timezone and keyboard layout.

> [!warning] Keep the clock in UTC
> As covered in the [[Bios Settings|BIOS settings]], the hardware clock stays on UTC and Proxmox handles time zones internally. This keeps all nodes in the cluster free of time drift.

![[Installation_4.jpg]]

### 5. Set the root password and administrator email

Set the root password and fill in an administrator email address. The default `mail@example.invalid` will be rejected by the installer, so a real address is required.

This address is where Proxmox sends its automated notifications. Out of the box that covers backup job results, storage replication failures, node fencing in an HA cluster, and available package updates.

![[Installation_5.jpg]]

### 6. Configure networking

Fill in the hostname, IP address, gateway and DNS server for the node, then start the installation.

Each node gets its own static address here. Since these values are the only thing that differs between the three installs, it is worth recording them as you go.

![[Installation_6.jpg]]

## After Installation

Once the installer finishes and the node reboots, the Proxmox web interface is reachable at `https://<node-ip>:8006`.