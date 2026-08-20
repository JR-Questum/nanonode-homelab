# Ansible

## Summary

Everything that happens to a [[Compute Node Module|compute node]] after [[installation|Proxmox is installed]] is done from here. The aim is that no node is ever configured by hand: the inventory describes what the homelab should look like, and a playbook makes the hardware agree.

## How the repository is laid out

```text
ansible/
├── ansible.cfg
├── requirements.yml          # collections this repo depends on
├── callback_plugins/         # custom console output
├── playbooks/
│   └── setup_nodes.yml
├── roles/
│   ├── configure_hostname/
│   ├── configure_chrony/
│   └── ...
├── private.example/          # inventory template, committed
└── private/                  # the real inventory, git-ignored
```

The only part that needs explaining is the `private` split. Everything identifying the actual homelab — hostnames, addresses, the vault with the root password — lives in `private/`, which git never sees. `private.example/` is the same tree with placeholder values, committed so the repository still makes sense to someone else, and to future me on a new laptop.

## Getting a control machine ready

Install the collections the roles use:

```bash
ansible-galaxy collection install -r requirements.yml
```

Create a real inventory from the template:

```bash
cp -r ansible/private.example ansible/private
```

Then fill in the real hostnames and addresses, create the vault holding the Proxmox root password, put the vault password at `~/.config/nanonode/vault_pass`, and make sure the management SSH key is at `~/.ssh/nanonode`. After that, [[Setup Nodes]] is a single command.
## Conventions

A few rules that all the roles follow, so that the next one has a shape to copy:

- **One role, one concern.** A role that needs a sentence with "and" in it to describe is usually two roles.
- **Variables are prefixed with the role name.** `defaults/` holds values meant to be overridden from the inventory; `vars/` holds derived values that are not.
- **Look before acting.** Is there a frequency-scaling subsystem, is ZFS loaded, is this node already a cluster member. A role that cannot apply cleanly should skip and say so, rather than fail — unless a wrong value would be worse than no value, in which case it asserts and stops the run with a useful message.
- **Roles own their reboots.** If a change needs a restart to take effect, the role that made the change performs it and waits for the node to come back. Nothing is left as a note for the operator to remember.
- **Secrets come from the vault**, never from a role default.

## The console output

`ansible.cfg` uses a custom stdout callback that lives in `callback_plugins/` and renders a run as a NieR:Automata style boot sequence: one line per task, a typewriter effect, and — with the timing report set to list everything — a closing rundown of every task that ran, in execution order. It is entirely cosmetic. It changes how results are printed, never what runs, and commenting out one line in `ansible.cfg` returns the standard output, and yes this is vibe coded. 