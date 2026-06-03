# 1U Compute Node Module

## Summary

The Compute Node Module is intended to provide compact compute capacity running Proxmox containers, powered via USB-C PD from the [[Power Delivery Module]].

Instead of relying on traditional server hardware with high power consumption and large physical footprints, this design introduces three identical compute nodes running containerized workloads. Each node receives power from the centralized [[Power Delivery Module]] through a dedicated USB-C PD channel.

The goal is to create a more efficient, space-conscious, and observable compute layer for the homelab.

## Goals

The module is designed with the following goals in mind:

- compact physical size
- low power consumption
- container isolation and remote management via proxmox
- hardware monitoring
- high availability

## Design Principles

### Independent compute per node

Each node should run its own instance of Proxmox with isolated container workloads. This ensures that the operation or failure of one node does not directly impact the compute capacity of the others.

### Unified power delivery via USB-C PD

All compute nodes should receive power from the centralized [[Power Delivery Module]] through USB-C PD connections, eliminating the need for individual power adapters and maintaining a clean rack layout.

### Per-node observability

Each compute node should provide individual telemetry so that node-level resource usage can be monitored, visualized, and compared over time.

## Hardware Specifications

The current concept is based on the following hardware per node:

- [[Hardware overview#Lenovo thinkcenter m720q]]
- 24GB RAM
- 512GB storage

Further details regarding configuration and optimization will be documented as the build progresses.

## High-Level Architecture

### Compute Topology

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Power Delivery Module                            │
│                                                                             │
│ ┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐ │
│ │                 │         │                 │         │                 │ │
│ │    PD OUT 1     │         │    PD OUT 2     │         │    PD OUT 3     │ │
│ │                 │         │                 │         │                 │ │
│ └─────────────────┘         └─────────────────┘         └─────────────────┘ │
│          ●                           ●                           ●          │
└──────────┼───────────────────────────┼───────────────────────────┼──────────┘
           │                           │                           │           
           │                           │                           │           
           │                           │                           │           
           ▼                           ▼                           ▼           
  ┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐  
  │     Node 1      │         │     Node 2      │         │     Node 3      │  
  │  Lenovo M720Q   │         │  Lenovo M720Q   │         │  Lenovo M720Q   │  
  │     Proxmox     │         │     Proxmox     │         │     Proxmox     │  
  └─────────────────┘         └─────────────────┘         └─────────────────┘  
           ●                           ●                           ●           
           │                           │                           │           
           └───────────────────────────┼───────────────────────────┘           
                                       │                                       
                                       │                                       
                                       ▼                                       
                              ┌─────────────────┐                              
                              │     Network     │                              
                              │     Switch      │                              
                              │                 │                              
                              └─────────────────┘                              
```

## Functional Overview

### Physical chassis/enclosure

Each compute node is housed in a Lenovo M720q mini-PC chassis, providing a compact form factor suitable for space-constrained 10" rack environments. 

### Power delivery connection

Power is received from the [[Power Delivery Module]] via USB-C PD connection. Each node maintains its own independent PD negotiation with the power supply, ensuring stable and isolated power delivery. The USB-C PD connection eliminates the need for traditional AC power cables and external adapters.

### Network switch integration

All three compute nodes are connected to a shared network switch, enabling inter-node communication required for Proxmox cluster functionality. The switch provides the backbone for container migration, high availability features, and network service distribution across the compute layer.

### Storage configuration

Each node is equipped with 512GB of local storage, utilized for the Proxmox installation, container images, and local data storage. Storage configuration and optimization strategies will be documented as the deployment progresses.

### Remote access setup

Remote management capabilities are provided through Proxmox's built-in web interface and API, allowing for container lifecycle management, resource monitoring, and system administration from any network-connected device.

## Benefits

This design is expected to provide several practical benefits:

- reused enterprise hardware (cost-effective repurposing)
- compact 1U form factor
- dramatically lower power consumption compared to previous infrastructure
- Proxmox high availability across three nodes
- flexible container workloads

The power consumption improvement is particularly notable when compared to the previous setup, which utilized a DELL PowerEdge R410 Server with Dual Six Core X5650 2.6GHz processors, 2x 2TB SAS drives, 64GB RAM running ESXi. The new compute nodes achieve comparable functionality with significantly reduced energy requirements.