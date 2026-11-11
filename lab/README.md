# Hyper-V lab: the whole flow on one Windows PC

The lab is self-contained and **touches none of your existing infrastructure.**
AlmaLinux 10.2 stands in for RHEL 10.2. Same Anaconda, same `bootc`, same
Kickstart commands, no subscription needed.

```text
 Windows host (Hyper-V)
 ├─ "Default Switch" (NAT) ── uplink ──┐   internet for dnf / mirroring; cut off by lab_airgap.yml
 │                                     │
 │                          ┌──────────┴───────────┐
 │                          │ bootc-lab-pxe        │  AlmaLinux 10 (cloud image)
 │                          │ 10.77.0.10           │  TLS registry :5000 (lab CA, htpasswd)
 │                          │                      │  build host (podman, bootc-image-builder)
 │                          │                      │  PXE: tftp + httpd + dnsmasq (full mode)
 │                          │                      │  control node: tools container (podman)
 │                          └──────────┬───────────┘
 └─ "bootc-lab" (PRIVATE switch: no host NIC, no uplink, no router)
          ├─ bootc-lab-srv01  02:00:77:00:00:65  10.77.0.101  server       (Kickstart ostreecontainer)
          ├─ bootc-lab-ws01   02:00:77:00:00:66  10.77.0.102  workstation  (Kickstart bootc)
          └─ bootc-lab-vm01   02:00:77:00:00:6e  10.77.0.110  VM path: bib disk + cloud-init
```

The only DHCP server on `bootc-lab` is the PXE VM. Because it's a **Private**
switch, that DHCP can't reach your LAN or the host, and lab clients have no
route anywhere.

Budget: about 20 GB RAM with everything running (PXE 8, srv 4, ws 6, vm 4) and
about 250 GB of dynamic disk at most.

## 1. Prepare media (Windows)

```powershell
py lab/prepare_pxe_vm.py          # SSH key, AlmaLinux cloud image -> VHDX, cloud-init seed ISO
```

## 2. Network and PXE VM (Windows, Hyper-V Administrators; no admin shell needed)

```powershell
powershell -File lab/hyperv/New-BootcLabNetwork.ps1      # Private switch "bootc-lab"
powershell -File lab/hyperv/New-BootcLabPxeServer.ps1    # prints the SSH command
```

## 3. Copy the repo to the PXE VM and bring the lab up

From Git Bash on Windows (`IP` = the uplink IP that step 2 printed; get it
again later with `lab/hyperv/Get-BootcLabPxeIp.ps1`):

```bash
KEY=lab/.lab-secrets/id_ed25519
tar czf - --exclude=.git --exclude=lab/.media --exclude=artifacts . |
  ssh -i $KEY labadmin@$IP 'mkdir -p ~/bootc && tar xzf - -C ~/bootc && chmod 600 ~/bootc/lab/.lab-secrets/id_ed25519'
ssh -i $KEY labadmin@$IP
```

On the PXE VM:

```bash
cd ~/bootc
lab/run-tools.sh ansible-playbook -i lab/inventory lab/playbooks/lab_site.yml
```

`lab_site.yml` does the following (run it again and it changes nothing):

1. creates the lab CA and the registry certificate
2. starts a TLS registry with htpasswd auth
3. "mirrors" two dated AlmaLinux bootc bases and bootc-image-builder into the registry
4. downloads the AlmaLinux 10.2 boot ISO
5. builds an **internal RPM mirror** with exactly the packages the images need
   (resolved inside both bases), served at `http://10.77.0.10/bootc/repos/lab`.
   It also writes `images/repos/lab-airgap.repo`, so every build uses only that mirror.
6. configures the PXE server
7. builds **v1.0** of both images on the *older* base and promotes it to `:stable`

## 4. PXE-install the clients (Windows)

```powershell
powershell -File lab/hyperv/New-BootcLabClient.ps1 -Profile server
powershell -File lab/hyperv/New-BootcLabClient.ps1 -Profile workstation
vmconnect localhost bootc-lab-ws01      # watch shim -> GRUB -> Anaconda -> GDM
```

No keyboard input: the per-MAC GRUB file picks the profile, and Kickstart
does the rest. After the install, the same network boot falls through to the
local disk, because a boot loader is now there (`state: install`).

## 5. Airgap, then patch → deploy → roll back (PXE VM)

```bash
lab/run-tools.sh ansible-playbook -i lab/inventory lab/playbooks/lab_airgap.yml -e airgap=on
lab/run-tools.sh ansible-playbook -i lab/inventory lab/playbooks/lab_patch_cycle.yml
```

`lab_patch_cycle.yml` steps (each also runs on its own with `--tags`):

| Tag | Step | Expected |
| --- | --- | --- |
| `patch` | build v1.1 on the newer mirrored base → `:testing` | RPM diff report shows the six weeks of errata |
| `promote` | `:testing` → `:stable` by digest | `:stable-previous` = v1.0 |
| `upgrade` | `bootc upgrade` + reboot, one host at a time | booted digest = v1.1, health check passed |
| `rollback` | `bootc rollback` + reboot | booted digest = v1.0 |
| `badimage` | re-upgrade to v1.1, then build and promote v1.2-bad (forced failing health check) and upgrade | hosts boot v1.2-bad, fail the check, **roll themselves back** to v1.1 |
| `fleetrb` | `promote_rollback=true` points `:stable` back at v1.1 | upgrade check stages nothing |

With the airgap on, the patch builds pull the base from the lab registry and
packages from the lab RPM mirror. That's the production pattern (internal
registry + Satellite/Pulp mirrors behind `images/repos/`). The "patch" here is
the newer mirrored base: real errata, carried in the way oc-mirror would.

## 6. VM path (bootc-image-builder + cloud-init)

```bash
# PXE VM (airgap can stay on: bib runs from the mirrored image)
lab/run-tools.sh ansible-playbook -i lab/inventory ansible/playbooks/image_disk.yml
```
```powershell
# Windows
scp -i lab/.lab-secrets/id_ed25519 labadmin@${IP}:/var/lib/bootc-build/output/server-stable/disk.vhdx lab/.media/bootc-vm.vhdx
powershell -File lab/hyperv/New-BootcLabVmFromImage.ps1
```

This is the KubeVirt flow with Hyper-V in OpenShift's place: the same disk,
and cloud-init NoCloud for Day-1.

## Teardown

```powershell
powershell -File lab/hyperv/Remove-BootcLab.ps1     # only bootc-lab-* VMs, their disks, and the bootc-lab switch
```

## Lab limits (and what covers them)

| Not in the lab | Why | Where it's covered |
| --- | --- | --- |
| UEFI HTTP Boot | Hyper-V Gen2 only does PXE | DHCP snippets; test on KVM/OVMF or hardware |
| RHEL base + entitlements | no subscription needed for the lab | the same Containerfiles, with `BASE_IMAGE` = RHEL |
| OpenShift Virtualization | no cluster here | `bootc_kubevirt_image` role, `kubevirt/` YAML |
| Legacy BIOS PXE | Gen2 is UEFI-only | Molecule checks the `grub2-mknetdir` path |
