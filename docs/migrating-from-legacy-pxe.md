# Migrating from the legacy RPM PXE setup

## What stays the same

- **The network boot itself.** DHCP still hands out next-server and filename,
  TFTP/HTTP still serve shim + GRUB + kernel + initrd, and Anaconda still
  reads a Kickstart.
- **Kickstart for storage and Day-1 identity**: partitioning, network,
  hostname, admin account, SSH keys.
- **The PXE server can sit next to the old one.** bootc content lives under
  its own TFTP subdirectory (`bootc/`) and HTTP alias (`/bootc`), so the two
  setups don't collide on one host either.

## What changes

| Legacy | bootc |
| --- | --- |
| `url --url=http://repo/...` + `%packages` (hundreds of RPMs) | `ostreecontainer --url=<registry>/bootc/<profile>:stable` (or `bootc --source-imgref=...`); **no `%packages`** |
| Long `%post` scripts that configure the host | Configuration is in the image (`images/*/rootfs`, `Containerfile`). `%post` only writes the pull secret and sudoers |
| Patch with `dnf update` on each host | Patch the image once; hosts `bootc upgrade` |
| Roll back = restore from backup / rebuild | `bootc rollback` + reboot (and an automatic rollback on a failed health check) |
| Each host slowly drifts | `/usr` is read-only and identical on every host with the same digest |
| Separate VM templates | Same image → `bootc-image-builder` → VM disk |

## Side by side

Legacy:

```text
url --url=http://repo.internal/rhel9/BaseOS
repo --name=AppStream --baseurl=http://repo.internal/rhel9/AppStream
%packages
@^minimal-environment
chrony
...
%end
%post
# 300 lines of configuration
%end
```

bootc (rendered by `bootc_pxe`):

```text
reqpart --add-boot
part / --grow --fstype=xfs
ostreecontainer --url=registry.internal:8443/bootc/server:stable --transport=registry
%pre   # registry CA + pull secret for the installer
%post  # pull secret on the host for later upgrades
```

## Moving hosts across

1. Port each host role's `%post` and `%packages` into the image:
   - packages → `dnf install` in the Containerfile
   - config files → `rootfs/etc/...` (or `rootfs/usr/...` if they should be immutable)
   - services → `systemctl enable` in the Containerfile
2. Build and test it (`make images`, then the lab).
3. For each host:
   - add it to `bootc_pxe_hosts` with `state: reinstall` (the disk already has
     a boot loader, so `install` would skip it)
   - PXE-boot it
   - set it back to `state: install` (or `local`)
4. Put the old Kickstart and the RPM repo snapshot in an archive. Retire them
   when the last RPM host is gone.

Back up `/home` and any `/var` data first: a reinstall wipes `disk`.
