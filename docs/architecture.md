# Architecture and decisions

## The problem

Today, airgapped hosts are installed by PXE + an RPM Kickstart and patched in
place with `dnf`. Over time, hosts in the same role drift apart. A bad update
is hard to undo. Bare metal and VMs are built in different ways.

The new platform is OpenShift (OCP). We still need to provision:

- **user workstations**: physical desktops, and VMs on OpenShift Virtualization
- **a few physical workstations / servers** that aren't OCP nodes
- **VMs on KubeVirt** (OpenShift Virtualization)

## The approach

The OS is a container image. `images/base/Containerfile` defines the server
image and `images/workstation/Containerfile` adds GNOME on top. Both are built
on Red Hat's `rhel10/rhel-bootc` base. CI pushes them to the internal registry
with an immutable version tag, and hosts follow a **channel tag**
(`:testing`, `:stable`).

From that one image:

- **Bare metal** network-boots the stock RHEL 10 installer. A short Kickstart
  partitions the disk and runs `ostreecontainer` (or the newer `bootc` command),
  which pulls the image straight onto disk. There's no `%packages`.
- **VMs** use the same image, converted to a disk with `bootc-image-builder`.
  On OpenShift Virtualization it becomes a golden `DataSource`. cloud-init does
  Day-1 (hostname, user, keys, pull secret).
- **Day-2** is the same everywhere. `bootc upgrade` stages the new image next
  to the running one and a reboot switches to it. `bootc rollback` switches back.
  A health check rolls back on its own if a new image boots unhealthy.

## Decision log

| # | Decision | Why | Alternatives considered |
| --- | --- | --- | --- |
| 1 | RHEL 10 image mode (`bootc`) as the OS for everything outside OCP nodes | One artifact, built and scanned in CI; read-only `/usr`; atomic updates and rollback | Keep RPM Kickstart + dnf; Satellite content views alone don't remove drift |
| 2 | PXE server is a **standalone RHEL host**, not a pod on OCP | Hosts can still be rebuilt when the cluster is down; no L2/Multus plumbing into OCP for DHCP/TFTP; sits next to the existing PXE setup | Containerized PXE on OCP (later option; the role's output is plain files) |
| 3 | **Existing DHCP stays authoritative**; the role renders snippets (Kea, ISC, Infoblox) and can run proxy-DHCP | DHCP is owned by another team and is shared; no second authoritative server | Role-managed Kea/dnsmasq (allowed only on isolated networks: `bootc_pxe_dhcp_mode: full`) |
| 4 | Workstations are a **GNOME image layered `FROM` the server image** | One patch flows to both; the workstation diff is small and reviewable | Separate workstation base; headless + VDI |
| 5 | KubeVirt VMs use **qcow2 → DataVolume → golden DataSource** + `cloudInitNoCloud` | Native OpenShift Virtualization pattern; fast clones; VMs then follow the registry tag for updates | containerDisk only (ephemeral root); PXE-booting VMs over Multus (slow, needs L2) |
| 6 | **Channel tags + promotion by digest** (`:testing` → `:stable`) | What was tested is exactly what ships; fleet rollback = retag | Rebuild for prod; pin every host to a digest (supported via `bootc switch`, more toil) |
| 7 | **Shim and GRUB come from the boot ISO** | Secure Boot works with Microsoft-signed shim; no extra RPMs to mirror; versions match the installer | grub2-efi/shim RPMs on the PXE host |
| 8 | Per-MAC GRUB files with `state: install` = **install only onto a blank disk** | Zero-touch installs that are safe with network-first boot order; reinstalling is a deliberate `state: reinstall` | Toggling DHCP filenames; manual boot-menu choice |
| 9 | Image-side **health check with automatic rollback** (`bootc-health-check.service`) | A bad image can't strand a remote host; checks are drop-in scripts | greenboot (check whether RHEL 10 packages it for bootc; can replace ours if so) |
| 10 | All tooling runs in a **pinned Python 3.14 container** | Same Ansible/linters everywhere; host Python stays clean | Host Ansible; per-user venvs |

## Components

| Component | Runs on | Talks to |
| --- | --- | --- |
| Internal registry (Quay / OCP mirror registry) | existing | build host (push), installers + hosts (pull) |
| Build host (`bootc_image_build`) | RHEL 9/10 with podman, entitled or with internal repo mirrors | registry |
| PXE / HTTP server (`bootc_pxe`) | RHEL 9/10 | DHCP (via snippets), clients over TFTP/HTTP |
| Control node | the tools container | everything over SSH / Kubernetes API |

## Security notes

- The **pull secret** is published to the installer over HTTP, restricted to
  `bootc_pxe_allowed_networks`. Use a **read-only robot account** scoped to the
  bootc repositories. If you need more, serve `/bootc/trust` over HTTPS, or bake
  a pull-only credential into a dedicated installer image.
- The **registry CA** is baked into the image's trust store at build time
  (`bootc_build_registry_ca`) and fetched by the installer in `%pre`.
- SSH: keys only, no root login (`40-bootc-hardening.conf`). The admin account
  is key-only with NOPASSWD sudo unless you set `bootc_pxe_admin_password_hash`.
- Image signing (cosign / sigstore) plus a `policy.json` on hosts is the next
  step. Set `bootc_pxe_signature_verification: true` once signing is in place.
