# Workstations (physical and VM)

The workstation image is `images/workstation/Containerfile`, built `FROM` the
server image. Every server patch flows into it, and its own diff stays small:
GDM, GNOME Shell, Ptyxis (the terminal in EL10), Nautilus, Firefox, and the
graphical target.

## Physical workstations

Add the workstation to `bootc_pxe_hosts` with `profile: workstation` and its
`disk`, then PXE-boot it. The Kickstart creates the admin account. For local
login on the console, set `bootc_pxe_admin_password_hash` (`openssl passwd -6`),
or join the host to IdM in a later step (below).

## Workstation VMs (OpenShift Virtualization)

Build the disk once per version and publish it as a DataSource:

```bash
ansible-playbook -i inventory/<site> playbooks/image_disk.yml -e bootc_build_disk_profile=workstation
ansible-playbook playbooks/kubevirt_golden_image.yml -e bootc_kubevirt_name=bootc-workstation \
  -e bootc_kubevirt_version=<version> -e bootc_kubevirt_source_url=<disk url>
```

Users reach VM desktops through your VDI or console tooling. The image is the
same as on physical workstations.

## Updates without kicking users out

On workstations, `bootc-fetch-apply-updates.timer` is enabled with a
**stage-only** override: it downloads and stages the new image overnight, and
the update applies at the user's **next reboot**.

`day2_upgrade.yml` also skips the reboot on any host where someone is logged in
to a graphical session. The update stays staged and the host is reported.
`-e bootc_lifecycle_force_reboot=true` reboots anyway (maintenance windows).

## What users keep across updates and rollbacks

| Path | Survives `bootc upgrade` / `rollback`? |
| --- | --- |
| `/home` (→ `/var/home`) | Yes, user data is never touched |
| `/var` (logs, caches, app state) | Yes, not versioned. Rollback doesn't undo `/var` changes |
| `/etc` | Merged on upgrade (local changes kept). Rollback returns the previous deployment's `/etc` |
| `/usr` (the OS) | Replaced atomically by the image |

## Identity (next step)

To log in with directory accounts, add `sssd`, `ipa-client` / `realmd` and
`oddjob-mkhomedir` to the workstation image, and enroll at first boot. On
metal, a Kickstart `%post` or a first-boot unit does this with a one-time OTP.
On VMs, cloud-init `runcmd` does it. Keep enrollment secrets out of the image.
