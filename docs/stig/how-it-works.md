# How STIG hardening works in this repo

This is the technical guide for engineers. For the ISSO view, start with
[README.md](README.md). For why it's done this way, see
[trade-study.md](trade-study.md).

## The pieces

```text
compliance/stig/controls.yaml ──► tools/stig_report.py ──► images/stig/tailoring.xml
  (decisions, per STIG ID)          (make stig)             docs/stig/finding-map.md
compliance/stig/disa/…xccdf.xml ─┘                          docs/stig/checklists/*.cklb
compliance/stig/ssg/*.json ──────┘
compliance/stig/results/*.json ──┘  ◄── lab/playbooks/lab_stig_scan.yml (scans)

images/base ──► images/workstation
     │                 │
     └─► images/stig ◄─┘   (STIG_PROFILE=stig | stig_gui, always the LAST layer)
              │
              ▼
   registry: bootc/server-stig, bootc/workstation-stig
              │
              ▼
   bootc_pxe Kickstart (stig: true): STIG disk layout, fips=1 installer
```

### 1. The image layer (`images/stig/Containerfile`)

1. It installs `openscap-utils` and `scap-security-guide` from the same repos
   as the rest of the build. In an airgap that is the internal mirror under
   `images/repos/`.
2. It runs **`oscap-im`** with the profile `stig_site` (server) or
   `stig_gui_site` (workstation). Those are the DISA STIG profiles as tailored
   in `tailoring.xml`.
   - `oscap-im` evaluates every rule and applies the fixes it can apply in a
     container build.
   - Red Hat's content has a `bootc` fix type for rules that need one. For
     example, the kernel arguments (`audit=1`, `pti=on`, `page_poison=1`, …)
     land in `/usr/lib/bootc/kargs.d/`, and services are enabled, not started.
3. `stig/rootfs/` adds what the build can't decide by itself:
   - `usr/lib/bootc/kargs.d/01-fips.toml` adds `fips=1`. OpenSCAP sets the FIPS
     crypto policy; the kernel argument has to come from the image.
   - `etc/usbguard/rules.conf` is a written device policy (hubs, keyboards and
     mice, smart card readers). A policy generated at build time would see no
     devices and lock out every USB keyboard.
4. **A second OpenSCAP pass.** `oscap-im` marks the audit rules and `auditd.conf`
   settings "notapplicable" in a build, although hosts are scanned against them.
   A normal `oscap xccdf eval --remediate` applies exactly those rules (see
   "What the lab found" below).
5. It removes the build-only packages: `openscap-utils` pulls in `rpm-build` and
   friends. It keeps the scanner and the content (`openscap-scanner`,
   `scap-security-guide`) so hosts can be scanned.
6. `bootc container lint` runs last.

The build keeps a short record in the image, under `/usr/share/bootc-stig/`:
- `build-results.txt`: each rule's result during the build
- `tailoring.xml`
- `profile.env`
- `ssg-version`

**Reading the build log.** Rules shown as `error` during the build are
usually fixes whose *persistent* half worked but whose *live* half can't run
in a container. Examples:
- `sysctl -w`: the `/etc/sysctl.d/` file is written, and takes effect at boot
- `systemctl start`: the unit is enabled
- `grubby`: the kernel argument is written to `kargs.d`

The scans of the image and of the hosts are the authority, not the build log.

**Why the STIG layer goes last.** A package installed after hardening can bring
its own defaults or services, which undoes the hardening. The workstation
image therefore builds `FROM workstation` and adds the STIG layer on top. It
does not build GNOME on top of `server-stig`. The `stig_gui` profile is the
same as `stig` except that it keeps GDM, NFS and the graphical boot target.

### 2. Install templates (`bootc_pxe`, `stig: true`)

An image can't partition a disk. For images marked `stig: true` in
`bootc_pxe_images`, the role does three things:

- **Disk layout.** It uses `bootc_pxe_partitioning_stig` from
  `ansible/roles/bootc_pxe/defaults/main.yml`:
  - separate `/var`, `/var/log`, `/var/log/audit`, `/var/tmp`, `/tmp` and `/var/home`
  - `nodev`, `nosuid` and `noexec` where DISA requires them
  - `/boot` with `nodev,nosuid`
  - In image mode `/home` is a link to `/var/home`, so `/var/home` is the separate volume.
- **FIPS installer.** It boots the installer with `fips=1`, so keys made during
  the install (SSH host keys, for example) are FIPS-generated.
- **Admin password.** It refuses to render without
  `bootc_pxe_admin_password_hash`, because STIG forbids passwordless sudo.

`tools/render_check.py` fails CI if a STIG Kickstart loses any of the separate
file systems or gains `NOPASSWD`.

### 3. Decisions (`compliance/stig/controls.yaml`)

- **The default.** Every DISA finding is met by `image-openscap` unless
  `controls.yaml` says otherwise.
- **Entries.** An entry records a different disposition: an image file,
  Kickstart, a site setting, an exception, or not applicable. It also records
  a plain-language note, where in git the finding is met, and for exceptions
  the approval status.
- **Tailoring.** `deselect:` and `values:` on an entry become the tailoring
  file. Each tailoring change therefore sits next to the finding that
  justifies it, and `stig_report.py check` refuses a deselect that doesn't
  belong to that finding's STIG ID.

### 4. Evidence

`lab/playbooks/lab_stig_scan.yml` scans with the same content and tailoring:
- **the images in the registry** with `oscap-podman`: the plain server image
  (the "before"), `server-stig` and `workstation-stig`
- **the running hosts** with `oscap xccdf eval`: srv01, ws01 and the RPM
  comparison host

It then:
- writes each target's rule results to `compliance/stig/results/<target>.json`
- regenerates the finding map and one STIG Viewer checklist per target
- keeps the full ARF/HTML reports in `artifacts/stig/<date>/`; they're too big
  for git, so attach them to the evidence package

CI runs a lighter check on every pull request:
- it builds `server-stig` on the AlmaLinux base
- it scans the image from inside (container context)
- it uploads the reports
- `make stig-check` fails if `controls.yaml` is invalid or any generated file is
  stale

## Changing something

| You want to… | Do this |
| --- | --- |
| Turn off a rule for a good reason | Add `deselect: [rule_id]` under its STIG ID in `controls.yaml`, with `disposition: exception`, a `note` and `approval: proposed`. Run `make stig`, then open a PR for the ISSO to review. |
| Change a value (e.g. password length) | Add `values: {var_name: value}` under the STIG ID. Find variable names in the HTML report or the SSG guide. Run `make stig`. |
| Meet a finding another way | Set its `disposition` and `where` in `controls.yaml`, and add the file (image or template). |
| Pick up a new DISA release | Mirror the new `scap-security-guide`. Run `stig_report.py extract-ssg` on its data stream. Put the new DISA XCCDF in `compliance/stig/disa/` and point `controls.yaml` at it. Run `make stig`; the PR diff shows what changed. |
| Fix a finding on the fleet | Fix it in git. Then build → `:testing` → promote → `bootc upgrade` ([day2.md](../day2.md)). Don't fix hosts by hand. |

## Image mode vs. an RPM-installed host

| Topic | RPM-installed host (`bootc-lab-rpm01`) | bootc host (`srv01`, `ws01`) |
| --- | --- | --- |
| Where hardening happens | On each host: the Ansible Lockdown STIG role after install (today's RHEL 8 practice), re-run over the host's lifetime | Once, in the image build. Every host gets identical bits. |
| Patching | `dnf update` on the host. New packages can bring new defaults that need re-hardening. | New image built and scanned in CI *before* any host gets it. `bootc upgrade` swaps it in atomically, and `bootc rollback` swaps it back. |
| Drift | Any file can change. Rescans catch it after the fact. | `/usr` is read-only. Only `/etc` and `/var` can drift. |
| Evidence | Per-host scans | Image scan (covers every host on that digest) plus host scans for `/etc`, `/var`, mounts and kernel state |

Things that behave differently in image mode, and how the finding map treats
them:

- **`/etc` is merged on upgrade, not replaced.** A local edit to a file in `/etc`
  survives `bootc upgrade` (3-way merge). Host scans catch it. Prefer settings in
  `/usr` where the software supports it, and keep host scans scheduled.
- **AIDE (file integrity, RHEL-10-200630).** The AIDE database is created in the
  build and lands in `/var/lib/aide` on the first install only. After an
  upgrade, AIDE reports the new image's files as changed. The image digest,
  verified by `bootc`, is the stronger integrity control for `/usr`. On a bootc
  host AIDE matters mostly for `/etc` and `/var`.
- **Package rules** (`gpgcheck`, "remove package X") are evaluated against the
  image's RPM database and pass or fail the same way on every host. `dnf` isn't
  used on hosts.
- **Kernel arguments** come from `kargs.d` in the image. `grubby` isn't used.

## What the lab found: STIG + image mode gotchas

These all broke something in the lab, and every one of them would break in
production too.

| Symptom | Cause | Fix in this repo |
| --- | --- | --- |
| SSH key login refused on every STIG host (`Permission denied (publickey)`), with the DoD banner showing | FIPS mode: OpenSSH accepts no **Ed25519** keys | Admin keys must be **ECDSA (P-256/384) or RSA ≥ 3072**. The lab clients use an ECDSA P-384 key (`lab_admin_pubkey_fips`). |
| Anaconda stops with "Bootc installation does not yet support user-specified mount points: /tmp, /var/home, /var/log, /var/log/audit, /var/tmp" | The newer Kickstart **`bootc`** command (10.2) can't create extra mount points | STIG images must use **`ostreecontainer`**. `bootc_pxe` refuses `stig: true` plus `ks_directive: bootc`, and so does `render_check.py`. |
| The health check failed on the first boot ("cannot read bootc status"); updates from a systemd timer would too | From a service, `bootc` re-executes a copy of itself (SELinux `install_t`) from `$TMPDIR`. The STIG makes `/tmp` **`noexec`**, so that `execve` fails. | `bootc-health-check.service` and `bootc-fetch-apply-updates.service` get a private `RuntimeDirectory` on `/run` and `TMPDIR` pointing at it |
| About 85 audit findings Open on every host (no STIG audit rules, `auditd.conf` untouched) | In its build mode `oscap-im` marks the audit rules, the `auditd.conf` settings and three logging rules **notapplicable**. Hosts are still scanned against them, and their fixes are plain files under `/etc/audit` | The Containerfile runs a **second OpenSCAP pass** (`oscap xccdf eval --remediate`) on exactly the rules `oscap-im` skipped in those families. The rule list comes from the build's own results. |
| A STIG setting in `/etc/dnf/dnf.conf` disappeared | The build restored a backup of `dnf.conf` after hardening, which undid OpenSCAP's change | Remove only the line the build added |
| AIDE baseline missing on hosts | An image's `/var` content isn't copied at install | `bootc-aide-init.service` creates the baseline on first boot |
| Boot loader password | Image mode's boot loader config (bootupd) reads `/boot/grub2/user.cfg` but names the superuser `root` | The Kickstart writes `user.cfg` from `bootc_pxe_grub_password_hash`. The superuser name is an exception (RHEL-10-600010). |
| `oscap-im` stops with "supposed to be used only in the bootable container build environment" | It runs only in a **podman/buildah** build, not a Docker one | Build the STIG layer with podman: the lab build host and the CI `stig-image` job both do |
| One `sshkey` per user | Kickstart (`ksvalidator`) refuses a second `sshkey` line for the same user | One key in Kickstart. Add more through IdM or `%post`. |
| Ansible `become` needs a password | STIG forbids `NOPASSWD` sudo | `ansible_become_password` from a vault. `bootc_pxe` refuses a STIG install without a password hash. |

## RHEL vs. the AlmaLinux lab

The lab runs AlmaLinux 10.2 as a free stand-in for RHEL 10.2. Its
`scap-security-guide` 0.1.82 is Red Hat's content rebuilt with AlmaLinux names:
the same rules and the same DISA STIG IDs. Expect these differences on real RHEL:

- **FIPS.** AlmaLinux turns FIPS mode on, but its crypto modules aren't
  FIPS 140-3 validated. On RHEL they are, which is what RHEL-10-000500 actually
  requires.
- **Vendor and GPG key rules.**
  - `installed_OS_is_vendor_supported` passes on RHEL only.
  - The GPG-key rule checks AlmaLinux's key instead of Red Hat's.
  - `subscription-manager` is installed but does nothing on AlmaLinux.
- **The data stream file name** is `ssg-rhel10-ds.xml` on RHEL. The Containerfile
  picks it from `/etc/os-release`. The scan playbook and `controls.yaml` name
  the AlmaLinux one, so change those two when moving to RHEL.
