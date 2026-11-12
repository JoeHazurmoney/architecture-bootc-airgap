# Day-2: patch, deploy, roll back

The whole lifecycle is four playbooks. Nobody needs to type `bootc` on a host.

```text
 base image refreshed (mirrored)       image_patch.yml          image_promote.yml
 or Containerfile change      ───▶  build → lint → RPM diff ───▶  :testing ──▶ :stable
                                    push :<version>, :testing     (by digest, no rebuild)
                                                                        │
                    day2_upgrade.yml (canary, then 25% batches) ◀───────┘
                    bootc upgrade → reboot → digest + health check
                                    │ unhealthy?
                                    ▼
            host rolls itself back (bootc-health-check.service)
            day2_rollback.yml       (operator-driven host rollback)
            image_promote.yml -e promote_rollback=true   (fleet/channel rollback)
```

## 1. Patch the image

Patches come from three places:

| Source | How it enters | What you run |
| --- | --- | --- |
| Red Hat refreshes `rhel-bootc:10.x` (errata rolled in) | mirror the new dated tag/digest (see [airgap-content.md](airgap-content.md)), update `bootc_build_base_image` | `image_patch.yml` |
| Errata between base refreshes | internal repo mirrors in `images/repos/` | `image_patch.yml -e '{"bootc_build_args": {"APPLY_UPDATES": "true"}}'` |
| Our own changes | a Containerfile / `rootfs` change in git | `image_patch.yml` (CI) |

`image_patch.yml` (role `bootc_image_build`, `bootc_build_action: build`):

1. pulls the base image from the mirror and records its digest
2. builds **server**, then **workstation** on top of the new server image, then
   the STIG-hardened **server-stig** and **workstation-stig** (the STIG layer goes
   last; see [stig/how-it-works.md](stig/how-it-works.md))
3. each build ends with `bootc container lint`
4. diffs the RPMs against the current `:testing` image and writes
   `/var/lib/bootc-build/reports/<version>-<profile>-rpm-diff.txt`
   (`+` added, `-` removed, `~` changed)
5. pushes the immutable tag `:<release>-<YYYYMMDD>.<HHMM>`
6. moves `:testing` to that digest (registry-side copy, digest preserved)

For STIG hosts, scan the new `:testing` images before promoting:
`lab/playbooks/lab_stig_scan.yml --tags images -e stig_scan_tag=testing` in the
lab, or your Lightspeed/Satellite compliance policy in production.

Test it: point a few canary hosts at `:testing` (`day2_switch.yml -e
bootc_lifecycle_switch_ref=<registry>/bootc/server:testing`), or build a
test VM from it.

## 2. Promote

`image_promote.yml` copies `:testing` to `:stable` **by digest**. The current
`:stable` is kept as `:stable-previous` first. Nothing is rebuilt, so
production gets exactly the bits that were tested.

## 3. Deploy to hosts

`day2_upgrade.yml` (role `bootc_lifecycle`, `bootc_lifecycle_action: upgrade`):

1. `bootc upgrade` stages the new image next to the running one. Only changed
   layers download, and the running system isn't touched.
2. It refuses an image this host already rejected (see automatic rollback).
3. Optionally checks the staged digest against `bootc_lifecycle_expected_digest`.
4. Reboots: `serial: [1, '25%']`, `max_fail_percentage: 0`. One canary, then
   batches, and any failure stops the rollout.
5. Waits for `bootc-health-check.service`, then checks that **the booted
   digest == the staged digest** and the health check passed.

Options:

- `-e bootc_lifecycle_reboot=false`: stage only. The update applies at the next reboot.
- `-e bootc_lifecycle_force_reboot=true`: reboot workstations even if someone is logged in.
- `day2_switch.yml -e bootc_lifecycle_switch_ref=<repo>@sha256:<digest>` pins
  hosts to an exact digest (strict change control).

Servers have the stock auto-update timer **disabled**, so Ansible decides when
they reboot. Workstations stage updates on a timer and apply them at the next
reboot (see [workstations.md](workstations.md)).

## 4. Roll back

There are three kinds of rollback, and they do different things:

| Kind | What it does | How |
| --- | --- | --- |
| **Automatic** (per host) | The new image boots, a health check fails, and the host runs `bootc rollback` and reboots into the previous image. A marker in `/var/lib/bootc-health/` makes sure it only happens once per digest | Built into the image: `bootc-health-check.service`. Add checks as executable `*.sh` in `/usr/lib/bootc-health.d/` (image) or `/etc/bootc-health.d/` (local) |
| **Host rollback** | Boot the previous deployment on chosen hosts | `day2_rollback.yml -l <hosts>` (asserts a rollback deployment exists, then verifies the booted digest afterwards) |
| **Fleet / channel rollback** | Point `:stable` back at the previous digest, so hosts stop picking up the bad image | `image_promote.yml -e promote_rollback=true` |

**Do both host and channel rollback for a bad release.** If you only roll back
hosts, the next `bootc upgrade` (or the workstation timer) stages the bad image
again. A host that auto-rolled-back refuses that digest in `day2_upgrade.yml`,
but the timer doesn't know that.

What rollback does **not** undo:

- `/var` (logs, databases, home directories). If an application migrated its
  data, rolling back the OS doesn't un-migrate it.
- Only **one** previous deployment is kept. Rolling back twice returns you to
  the newer image.

## Health checks

`/usr/libexec/bootc-health-check` runs after `multi-user.target`, waits for
boot to settle, then runs every executable check:

- image checks: `/usr/lib/bootc-health.d/*.sh` (server: `sshd`, `chronyd`;
  workstation adds `gdm`)
- local checks: `/etc/bootc-health.d/*.sh` (e.g. "my app answers on :8443")

Exit 0 = healthy. Anything else is unhealthy, and the script's output goes to
the journal (`journalctl -u bootc-health-check`). `bootc_lifecycle` prints it
when verification fails.

## Pilot checklist

The [Hyper-V lab](../lab/README.md) covers PXE (Secure Boot, per-MAC
zero-touch), both Kickstart directives, the airgap, patch → promote → upgrade
→ host rollback → automatic rollback → fleet rollback, and the VM path with
cloud-init. Still to check in the real environment:

- [ ] Build on `registry.redhat.io/rhel10/rhel-bootc` with entitled / internal repos
- [ ] Real hardware: NVMe/RAID partitioning, NIC firmware, Secure Boot with vendor firmware
- [ ] UEFI HTTP Boot (Hyper-V can't do it; needs real firmware or KVM/OVMF)
- [ ] `bootc_kubevirt_image` against the OpenShift Virtualization cluster
- [ ] DHCP snippets applied by the DHCP owners (Kea / Infoblox)
- [ ] Image signing + `policy.json` (`bootc_pxe_signature_verification: true`)
- [ ] Identity (IdM/SSSD) on workstations
