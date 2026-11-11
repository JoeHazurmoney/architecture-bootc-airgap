# Bare metal: PXE, UEFI HTTP Boot, Secure Boot, DHCP

## Boot chain

```text
firmware (UEFI PXE or HTTP Boot)
  └─ DHCP: next-server + filename          (snippets from bootc_pxe; existing DHCP)
      └─ BOOTX64.EFI  = Microsoft-signed shim (from the boot ISO)
          └─ grubx64.efi = Red Hat-signed GRUB (from the boot ISO)
              └─ grub.cfg: is there hosts/<mac>.cfg?
                  ├─ yes → per-host menu (zero-touch)
                  └─ no  → menu.cfg (defaults to "boot local disk")
                      └─ vmlinuz + initrd (HTTP) → Anaconda
                          └─ Kickstart: partition → ostreecontainer/bootc pulls the image
                              └─ %post: pull secret, sudoers, cloud-init off → reboot
```

## What the role puts where

| Path on the PXE host | Served as | Contents |
| --- | --- | --- |
| `/var/lib/tftpboot/bootc/EFI/BOOT/` | TFTP `bootc/EFI/BOOT/` | shim, GRUB, `grub.cfg`, `menu.cfg`, `hosts/<mac>.cfg` |
| `/var/www/bootc/EFI/BOOT/` | `http://<pxe>/bootc/EFI/BOOT/` | the same, for UEFI HTTP Boot |
| `/var/www/bootc/installer/<release>/` | `.../installer/<release>/` | `images/pxeboot/{vmlinuz,initrd.img}`, `images/install.img` (stage2), `.treeinfo` |
| `/var/www/bootc/ks/` | `.../ks/<profile>.ks`, `.../ks/hosts/<name>.ks` | Kickstarts |
| `/var/www/bootc/trust/` | `.../trust/` (allowed networks only) | `registry-ca.crt`, `auth.json` |
| `/root/bootc-pxe-dhcp-snippets/` | (not served) | Kea / ISC / Infoblox / dnsmasq-proxy snippets |

To review all of it without touching a server:

```bash
cd ansible && ansible-playbook -i inventory/<site> playbooks/render_check.yml -e bootc_pxe_render_dir=/tmp/render
```

## DHCP

The existing DHCP server stays authoritative. Give its owners the files in
`bootc_pxe_snippets_dir` (or fetch them with `bootc_pxe_fetch_snippets_to`):

| Client arch (option 93) | next-server | filename |
| --- | --- | --- |
| 7 / 9 (UEFI x64 PXE) | PXE host | `bootc/EFI/BOOT/BOOTX64.EFI` |
| 16 (UEFI x64 HTTP Boot) | – | `http://<pxe>/bootc/EFI/BOOT/BOOTX64.EFI`, plus option 60 `HTTPClient` |
| 0 (legacy BIOS) | PXE host | `bootc/bios/i386-pc/core.0` (with `bootc_pxe_bios_support: true`) |

If you can't change DHCP, set `bootc_pxe_dhcp_mode: proxy`. dnsmasq then
answers only the PXE question and leaves leases to the real server.
`full` mode (authoritative dnsmasq) is for isolated provisioning VLANs and the lab.

## Zero-touch installs: `bootc_pxe_hosts`

```yaml
bootc_pxe_hosts:
  - name: ws-0042
    mac: "3c:ec:ef:00:00:42"
    profile: workstation     # key of bootc_pxe_images
    disk: nvme0n1            # only this disk is touched
    state: install           # install | reinstall | local
```

- `install`: install **only if no local disk already has a UEFI boot
  loader**. With network-first boot order, the host installs once and then
  boots its disk on every later PXE boot. Safe to leave on.
- `reinstall`: always install (wipes `disk` on every network boot). Use it to
  rebuild or migrate a host, then set it back.
- `local`: always boot the disk.

Unknown MACs get the full menu, which **defaults to the local disk**. A stray
PXE boot never wipes anything.

Always set `disk` on real hardware. Without it, `clearpart --all` touches every disk.

## Secure Boot

Leave `bootc_pxe_secure_boot: true`. Clients get the Microsoft-signed shim
from the ISO, which verifies Red Hat's GRUB, which verifies the kernel. On
hypervisors, use the "Microsoft UEFI Certificate Authority" template (Hyper-V)
or the equivalent.

## Partitioning

The default is `reqpart --add-boot` + `part / --grow --fstype=xfs` on `disk`.
For RAID, LVM or separate `/var`, set `bootc_pxe_partitioning` to raw
Kickstart. Note that `/usr` is read-only and comes from the image, and `/var`
holds the host's state.

## Troubleshooting

| Symptom | Look at |
| --- | --- |
| No DHCP offer with a filename | option 93 match in the DHCP server; `log-dhcp` in dnsmasq modes |
| `shim` loads, then nothing (TFTP shows a request for `grubx64.efi` at the **root**) | The DHCP server sent the filename only as option 67. shim reads the BOOTP `file` field to find its directory. dnsmasq: `dhcp-no-override` (the role sets it). Kea `boot-file-name` and ISC `filename` already fill the field |
| `shim` loads, then "Failed to open \EFI\BOOT\grubx64.efi" | TFTP root/permissions; SELinux context (`restorecon -Rv /var/lib/tftpboot`) |
| GRUB prompt instead of a menu | `grub.cfg` next to `grubx64.efi`; per-host file name is the MAC in lowercase with colons |
| Installer can't fetch the image | Anaconda console (Alt+F2): `cat /tmp/bootc-ks-pre.log`; CA in `/etc/containers/certs.d/<registry>/`; `/etc/ostree/auth.json` |
| Installed, but `bootc upgrade` gets 401 | `/etc/ostree/auth.json` on the host (from Kickstart `%post`) |
