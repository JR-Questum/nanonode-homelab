# Proxmox API Prereqs

`ansible/roles/proxmox_api_prereqs`

## Summary

Prepares each node to be an API client of its own cluster: the Python libraries the Proxmox modules import, and the cluster's certificate authority in the system trust store.

## Why it exists

Everything up to this point was ordinary SSH work — installing packages, writing files, poking systemd. Cluster creation is different. It goes through the Proxmox REST API, and the modules that speak to it run *on the nodes themselves*, so each node needs `proxmoxer` and `requests` locally. Missing them produces an import error at the exact moment the cluster is being built, which is a poor time to find out.

The certificate half is the subtler reason. Proxmox generates its own certificate authority at install time and issues each node's API certificate from it. No public authority has signed anything, so a client that verifies certificates properly will refuse the connection. The common shortcut is to turn verification off everywhere. Instead this role copies the CA into the system trust store, so verification can stay on and still succeed.

## What it does

1. Installs `python3-proxmoxer` and `python3-requests`.
2. Reads the cluster CA from the first node in the `proxmox` group — read once, then distributed rather than regenerated per node.
3. Writes it into the local certificate directory on every node.
4. Runs `update-ca-certificates`, reporting a change only when something was genuinely added.

## Variables

| Variable | Default | What it changes |
| --- | --- | --- |
| `proxmox_api_prereqs_packages` | `python3-proxmoxer`, `python3-requests` | Libraries the Proxmox modules import |
| `proxmox_api_prereqs_trust_cluster_ca` | `true` | Whether to distribute the cluster CA at all |
| `proxmox_api_prereqs_ca_node` | first host in the `proxmox` group | Which node the CA is read from |
| `proxmox_api_prereqs_ca_source` | `/etc/pve/pve-root-ca.pem` | Where the CA lives on that node |
| `proxmox_api_prereqs_ca_dest` | `/usr/local/share/ca-certificates/pve-root-ca.crt` | Where it is installed on every node |

## Good to know

> [!note] The CA exists before the cluster does
> A standalone Proxmox install already has its own CA. When the cluster is created, the founding node keeps its authority and joining nodes get their certificates reissued from it. Copying the primary's CA out *before* the cluster exists is therefore correct rather than premature, it is already the right certificate.
