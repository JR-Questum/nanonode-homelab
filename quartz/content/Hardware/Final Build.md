# Final Build

## Summary

This page documents the finished **NANoNoDe** rack: a 6U 10" homelab rack containing three compute nodes, a centralized power delivery module, and the networking layer that ties them together.

Everything below has its own detailed write-up elsewhere in this vault. This page is the overview, or the starting point for anyone who wants to dig into a specific part of the build.

![[Final_build_booted.jpg]]

## Rack Layout

From top to bottom:

| Position | Module               | Details                                                               |
| -------- | -------------------- | --------------------------------------------------------------------- |
| 1        | Network switch       | [[Hardware overview#Ubiquiti UniFi USW Flex 2.5G 5\|USW Flex 2.5G 5]] |
| 2        | Keystone patch panel | 8 ports, 5 in use                                                     |
| 3        | POD 042              | [[Compute Node Module]]                                               |
| 4        | POD 153              | [[Compute Node Module]]                                               |
| 5        | POD 006              | [[Compute Node Module]]                                               |
| 6        | Power delivery       | [[Power Delivery Module]]                                             |

The frame itself is a 6U build of the MOD 10 10" rack design, printed in white ASA. The build is covered in [[Hardware/Compute/Build Log/iteration 3|compute It.3]].

## Node Identification

Each node is identified by a pod number on the left of the faceplate and its YoRHa unit designation and MAC address on the right, following the Nier:Automata theme that runs through the whole build.

| Pod     | YoRHa unit               |
| ------- | ------------------------ |
| POD 042 | YoRHa No.2 Type B (2B)   |
| POD 153 | YoRHa No.9 Type S (9S)   |
| POD 006 | YoRHa No.10 Type H (10H) |

Pairing each pod with its assigned unit means a node can be identified from across the room by its pod number, and matched to its network identity up close, without a single label sticker anywhere on the rack.

## Faceplates

The faceplates are printed in white ASA, with a laser-cut and engraved wooden insert dropped into the cutout. The design and engraving process is covered in [[Hardware/Compute/Build Log/iteration 2|compute It.2]].

The plain faceplates, before the wooden inserts were fitted:

![[Final_build_faceplates_no_wood.jpg]]

And with the final wooden pieces in place:

![[Final_build_faceplates_wood.jpg]]

The bottom unit carries its own insert with the three channel labels above the power switches, and the project name.

## Networking

The [[Hardware overview#Ubiquiti UniFi USW Flex 2.5G 5|USW Flex 2.5G 5]] sits at the top of the rack and patches down into the keystone panel below it.

``` text
                     ┌─────────────────────────────────────────┐                                          
                     │             USW Flex 2.5G 5             │         ┌───────────────────────────────┐
                     │   ┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐   │         │                               │
┌─────────┐          │   │  ●  ││  ●  ││  ●  ││  ●  ││  ●──┼───┼─2.5GbE──┤  USW Pro Max 16 POE (Uplink)  │
│         │          │   └──┼──┘└──┼──┘└──┼──┘└──┼──┘└─────┘   │         │                               │
│         │          └──────┼──────┼──────┼──────┼─────────────┘         └───────────────────────────────┘
│         │                 │      │      │      │                                                        
│ DESKTOP ├───────2.5GbE────┘      │      │      │                                                        
│         │                        │      │      │    ┌─────────────────┐                                 
│         │                        │      │      │    │                 │                                 
│         │                        └──────┼──────┼GbE─┤     POD042      │                                 
└─────────┘                               │      │    │                 │                                 
                                          │      │    └─────────────────┘                                 
                                          │      │    ┌─────────────────┐                                 
                                          │      │    │                 │                                 
                                          └──────┼GbE─┤     POD153      │                                 
                                                 │    │                 │                                 
                                                 │    └─────────────────┘                                 
                                                 │    ┌─────────────────┐                                 
                                                 │    │                 │                                 
                                                 └GbE─┤     POD006      │                                 
                                                      │                 │                                 
                                                      └─────────────────┘                                 
```


The switch is powered over PoE from the uplink on port 5, which means no separate power supply is needed for the networking layer. The compute nodes link at gigabit rather than 2.5 GbE, since that is what the [[Hardware overview#Lenovo thinkcenter m720q|M720q]] onboard NIC supports. The extra headroom on the uplink and desktop ports is still useful, and leaves room for faster nodes later.

## Power

All three nodes are powered from the [[Power Delivery Module]] over USB-C PD, with each node on its own fused and individually measured branch. There are no external power bricks anywhere in the rack.

At idle each node draws **under 5W**, which is a substantial improvement over the DELL PowerEdge R410 this cluster replaced.

Live measurements are shown on the front-mounted display and are also published to Home Assistant over ESPHome, so per-node consumption can be tracked and compared over time.

## Where To Read More

**Hardware**

- [[Hardware overview]] — component specifications
- [[Compute Node Module]] — compute layer design
- [[Power Delivery Module]] — power layer design
- [[Bios Settings]] — per-node BIOS configuration

**Build logs**

- [[Hardware/Compute/Build Log/iteration 1|Compute It.1]] — faceplate design and thermal testing
- [[Hardware/Compute/Build Log/iteration 2|Compute It.2]] — laser-cut frontplates
- [[Hardware/Compute/Build Log/iteration 3|Compute It.3]] — rack build and production faceplates
- [[Power Delivery/Build Log/iteration 1|Power It.1]] — ESPHome and display bring-up
- [[Power Delivery/Build Log/iteration 2|Power It.2]] — INA228 power monitoring
- [[Power Delivery/Build Log/iteration 3|Power It.3]] — prefboard assembly
- [[Power Delivery/Build Log/iteration 4|Power It.4]] — 1U chassis and final wiring

**Software**

- [[installation|Proxmox installation]] — base install per node

## What's Next

The hardware is finished. From here the work moves into software: clustering the three Proxmox nodes, configuring high availability on top of ZFS, and automating node configuration through Ansible so that a rebuilt node comes back identically without manual steps.
