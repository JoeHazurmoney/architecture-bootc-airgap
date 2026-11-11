# OpenShift Virtualization / KubeVirt

VMs use the **same image** as bare metal, delivered as a disk:

```text
bootc/server:<version>  ──bootc-image-builder──▶  disk.qcow2
disk.qcow2  ──CDI DataVolume (http or registry)──▶  PVC bootc-server-<version>
DataSource bootc-server  ──points at──▶  newest PVC
VirtualMachine  ──dataVolumeTemplates.sourceRef──▶  DataSource  (+ cloudInitNoCloud)
```

## Steps

1. **Build the disk** on the build host:
   `ansible-playbook -i inventory/<site> playbooks/image_disk.yml` (qcow2 by default).
2. **Publish it** in one of two ways:
   - HTTP: copy `disk.qcow2` under the PXE host's `/var/www/bootc/disks/...`.
   - Registry: wrap it with `images/containerdisk/Containerfile` and push
     `bootc/server-disk:<version>`. For a `registry` source, CDI needs
     `certConfigMap` (internal CA) and `secretRef` (pull credentials).
3. **Import** it and point the DataSource at it:
   ```bash
   ansible-playbook playbooks/kubevirt_golden_image.yml \
     -e bootc_kubevirt_version=<version> -e bootc_kubevirt_source_url=<url>
   ```
   Or apply [kubevirt/](../kubevirt/) through GitOps.
4. **Create VMs** from the `bootc-server` / `bootc-workstation` DataSource.
   Day-1 settings go in `cloudInitNoCloud`: hostname, user, SSH keys, and
   `/etc/ostree/auth.json` (use `userDataSecretRef` for the secret).

## Updating VMs

Existing VMs **don't need re-cloning**. Their disk tracks the registry tag, so
the Day-2 flow is identical to bare metal: run `day2_upgrade.yml` against them
(add them to `bootc_fleet`), or let the workstation timer stage updates.
Re-importing the DataSource only matters for **new** VMs, so they start on a
recent image.

## Notes

- `firmware.bootloader.efi.secureBoot: false` in the examples. Secure Boot in
  KubeVirt also needs the SMM feature. Enable both if your policy requires it.
- The image includes `qemu-guest-agent`, so OpenShift shows the guest IPs and OS info.
- The `bootc_kubevirt_image` role has been linted and checked with
  `--syntax-check`. It hasn't been run against a live cluster yet (see the
  pilot checklist in [day2.md](day2.md#pilot-checklist)).
