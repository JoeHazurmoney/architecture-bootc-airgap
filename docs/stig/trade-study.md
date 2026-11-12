# Trade study: how to apply the DISA STIG to image-mode (bootc) hosts

**Status:** recommendation adopted for this repo (decision #11 in
[architecture.md](../architecture.md)). Reviewers: platform engineering, ISSO.
**Benchmark:** DISA *Red Hat Enterprise Linux 10 STIG*, Version 1 Release 2
(434 findings: 30 CAT I, 399 CAT II, 5 CAT III).

## The question

The OS is now a container image built in CI and installed unchanged on every
host. How should STIG settings get into it, and how do we prove to the ISSO,
finding by finding, that they are there?

## What we need from the answer

| # | Criterion | Why it matters here |
| --- | --- | --- |
| C1 | **Supported by Red Hat** | Production runs RHEL 10. Findings raised against vendor content get vendor fixes. |
| C2 | **Fits image mode** | `/usr` is read-only on hosts, and changes made on a host are not in the image. Hardening has to happen in the build, or it has to be redone on every host after every upgrade. |
| C3 | **Traceable per finding** | The ISSO needs every DISA STIG ID (and V-ID) tied to where it's met and to scan evidence. |
| C4 | **GitOps** | Every setting and every deviation is reviewed in a pull request; the build is reproducible from git. |
| C5 | **Keeps up with new STIG releases** | DISA releases quarterly. Re-mapping 434 findings by hand each time does not scale. |
| C6 | **Works airgapped** | Content and tools come from the internal mirror; nothing is fetched at build or scan time. |
| C7 | **Evidence quality** | Scans that STIG Viewer and eMASS accept (XCCDF/ARF, CKLB), from the image *and* from running hosts. |

## The options

### A. OpenSCAP's image-mode tool (`oscap-im`) with Red Hat's STIG content, in the Containerfile

`oscap-im` ships in RHEL 10 (`openscap-utils`). Run in a Containerfile, it
evaluates the image against a profile and applies the fixes in build-safe form.
The SCAP Security Guide (`scap-security-guide`) content includes a dedicated
`bootc` fix type for rules that need one: kernel arguments go to
`/usr/lib/bootc/kargs.d/`, and services are enabled rather than started.
A tailoring file adjusts the profile without forking it.

- C1 ✅ Red Hat's documented way to harden image mode ("Security hardening and compliance of bootable images", RHEL 10 docs).
- C2 ✅ Designed for it.
- C3 ✅ Every SSG rule carries the DISA STIG ID; all 434 V1R2 findings map to SSG rules.
- C4 ✅ The tailoring file is generated from a YAML file in git.
- C5 ✅ Red Hat updates the content with each DISA release (V1R2 is in `scap-security-guide` 0.1.82).
- C6 ✅ Two RPMs from the mirror.
- C7 ✅ The same content scans the image (`oscap-podman`) and the hosts (`oscap xccdf eval`).
- ⚠️ It can't do install-time items: disk layout, disk encryption, accounts, boot loader password. Some fixes only half-apply in a build (`sysctl -w`, `systemctl start`); they persist and take effect at boot, but the build log shows them as "error".

### B. Hand-written config files in the image (`rootfs/` drop-ins)

Write sshd, PAM, audit, sysctl and so on ourselves, each file commented with the STIG IDs it meets.

- C1 ⚠️ Red Hat supports the OS, not our settings.
- C2 ✅ C4 ✅ Simple to review.
- C3 ⚠️ We'd maintain the mapping by hand for about 430 findings.
- C5 ❌ Every DISA release means re-reading the STIG.
- C7 ⚠️ We'd still need OpenSCAP to produce evidence.
- **Verdict:** right for the handful of items option A can't do, wrong as the main approach.

### C. Red Hat's official RHEL 10 STIG Ansible role, run at build time

The `RedHatOfficial.rhel10_stig` role on Ansible Galaxy is generated from the same SSG content as option A.

- C1 ✅ C3 ✅ C5 ✅ Same content, tagged by STIG ID.
- C2 ⚠️ Written for running hosts: it starts services, reloads daemons and checks live state. In a container build that needs Ansible in the build stage and many skips.
- **Verdict:** a good tool for the RPM-installed estate. For image mode, option A gets the same content without the friction.

### D. Ansible Lockdown `RHEL10-STIG` on running hosts (today's approach)

**This is how the site hardens RHEL 8 today:** MindPoint Group's community
Ansible Lockdown role (`RHEL8-STIG`, lightly modified), run against each host,
with the Lockdown Goss audit (`*-STIG-Audit`) as the check. The RHEL 10 release,
`RHEL10-STIG` 1.2.0, targets the same DISA V1R2. Every task is named and tagged
by STIG ID and V-ID, and each control has a toggle (`rhel10stig_000500` →
`RHEL-10-000500`), so it maps one-to-one onto the finding map.

The lab's comparison host `bootc-lab-rpm01` is hardened exactly this way
(`lab/playbooks/lab_rpm_lockdown.yml`).

- C1 ⚠️ Community content with a commercial support option (Lockdown Enterprise). Not Red Hat's. Its checks can disagree with Red Hat's scanner; the finding map shows both.
- C2 ❌ On a bootc host it can only change `/etc` and `/var` (`/usr` is read-only). Those changes aren't in the image, so they must be re-applied to every host, forever, and new hosts built from git don't have them.
- C3 ✅ Tagged by STIG ID.
- C5 ⚠️ It follows DISA releases on its own schedule, and the site's modifications must be ported each time (RHEL 8 → RHEL 10 changes every STIG ID anyway).
- **Lab finding:** with Lockdown's default `rhel10stig_disruption_high: false`, release 1.2.0 fails on two bugs in that code path (RHEL-10-300010 reads a skipped register; RHEL-10-300040 has an unbalanced parenthesis in a condition). Both are still on `devel` as of 2026-11-11. The lab runs with `disruption_high: true`.

### D2. The same Lockdown role, run inside the image build (keep the tool, move it)

The appealing middle path: keep the site's role and its modifications, but run
it once in the Containerfile instead of on every host. The role has a container
mode (`vars/is_container.yml` skips FIPS, partitions, `grubby`, firewalld and
service starts). The lab tried it, time-boxed: `images/stig-lockdown/`,
`lab/playbooks/lab_stig_lockdown_image.yml`.

What it took, in order of discovery:

| # | Problem in a `podman build` | Workaround |
| --- | --- | --- |
| 1 | The two default-path bugs above | `rhel10stig_disruption_high: true` |
| 2 | sshd config validation (`sshd -t`) needs host keys; an image has none | Generate temporary host keys, delete them after (host keys must never ship in an image) |
| 3 | "Fix files with no valid owner/group" walks the whole filesystem, bind mounts included, and can't `chgrp` read-only build inputs | Mount the inputs from a root-owned scratch stage |
| 4 | **The same walk changes files inside `/sysroot/ostree/repo/objects/`**, the image's content-addressed object store | None in the role. It isn't image-mode aware. |
| 5 | Every control that uses Ansible's systemd module fails ("Service is in unknown state"). That's 16 controls; the container mode skips 10 | Switch off the other 6, and do `systemctl enable/mask` in the Containerfile instead |
| 6 | The audit log ownership and mode controls expect `/var/log/audit/audit.log`, which only exists on a host | Switch off 2 controls |
| 7 | The role's handlers (`systemctl daemon-reload`, service restarts) need systemd as PID 1. Variables can't turn handlers off. | **Unsolved at the time-box.** It needs a patch to the role. |
| 8 | FIPS, kernel arguments, partitions and the boot loader password are skipped in a container | The same `kargs.d` and Kickstart pieces option A uses |

The 9 controls switched off are in `images/stig-lockdown/build-vars.yml`.

- **Verdict:** feasible only with a maintained fork that adds image-mode
  awareness: skip `/sysroot`, container-safe handlers, `systemctl` instead of the
  systemd module. The fork would also have to be re-checked against every new
  Lockdown release. Option A gets the same result with no fork, because Red Hat's
  content already has a `bootc` fix type. The site's Lockdown modifications
  carry over as entries in `controls.yaml` (tailoring) instead.

### E. Remediate running hosts from Red Hat Lightspeed (formerly Insights) or Satellite

Both can scan against the STIG profile and push remediation playbooks.

- C1 ✅ C7 ✅ Excellent for fleet-wide **reporting**.
- C2 ❌ Remediating a bootc host on the host has the same problem as option D.
- C6 ⚠️ Lightspeed is a SaaS service; airgapped sites use Satellite.
- **Verdict:** use them to **report** on hosts, not to fix them. Fixes go into git, then into the image.

### F. Kickstart OpenSCAP add-on, or image builder blueprints

The Anaconda `%addon com_redhat_oscap` and image builder's `[customizations.openscap]` harden package-mode installs and images.

- C2 ❌ Package mode only. For image mode, Red Hat points to `oscap-im`.
- **Verdict:** this is how the comparison host `bootc-lab-rpm01` is hardened, to show the traditional path.

## Scorecard

| | C1 Supported | C2 Image mode | C3 Traceable | C4 GitOps | C5 New releases | C6 Airgap | C7 Evidence |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| **A. `oscap-im` + SSG** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| B. Hand-written files | ⚠️ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ⚠️ |
| C. RHEL10 STIG role at build | ✅ | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ |
| D. Ansible Lockdown on hosts (today) | ⚠️ | ❌ | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ |
| D2. Ansible Lockdown in the build | ⚠️ | ⚠️ needs a fork | ✅ | ✅ | ⚠️ | ✅ | ⚠️ |
| E. Lightspeed / Satellite remediation | ✅ | ❌ | ✅ | ❌ | ✅ | ⚠️ | ✅ |
| F. Kickstart add-on / blueprints | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |

## Recommendation: A as the baseline, with four supporting layers

| Layer | Owns | In this repo |
| --- | --- | --- |
| 1. **Image build** (`oscap-im`, option A) | ~97% of findings: SSH, PAM, audit, sysctl, services, crypto policy, packages | [images/stig/Containerfile](../../images/stig/Containerfile) |
| 2. **Image files** (option B, small) | What the build can't decide alone: FIPS kernel argument, USBGuard device policy | [images/stig/rootfs/](../../images/stig/rootfs/) |
| 3. **Install templates** | Disk layout and mount options, FIPS during install, admin account | [bootc_pxe Kickstart](../../ansible/roles/bootc_pxe/templates/kickstart.ks.j2), `bootc_pxe_partitioning_stig` |
| 4. **Decisions in git** | Exceptions, site settings, tailoring, each with a plain-language reason | [compliance/stig/controls.yaml](../../compliance/stig/controls.yaml) |
| 5. **Evidence** | Scans of the image and the hosts, a finding map, STIG Viewer checklists | [finding-map.md](finding-map.md), [checklists/](checklists/) |

Lightspeed or Satellite (option E) can scan the running fleet on top of this.
Their findings flow back as pull requests to layer 4 or layer 1, never as
fixes on individual hosts.

## Measured in the lab (2026-11-12)

The same OpenSCAP content and tailoring scanned every system (AlmaLinux 10.2,
`scap-security-guide` 0.1.82, DISA V1R2, 434 findings). The full table is at
the top of [finding-map.md](finding-map.md).

| System | How it was hardened | ✅ Pass | ❌ Open |
| --- | --- | ---: | ---: |
| bootc server image, before the STIG layer | nothing | 107 | 161 |
| **bootc server (srv01)** | option A: image build + install templates | **357** | **5** |
| **bootc workstation (ws01)** | option A, `stig_gui` | **374** | **5** |
| RPM server (rpm01) | option D: RPM install + Ansible Lockdown `RHEL10-STIG` 1.2.0, `disruption_high: true`, Lockdown defaults + lab site values | 275 | 104 |

The same hosts through the **Ansible Lockdown audit** (Goss, `RHEL10-STIG-Audit`,
the site's current scanner; 974 tests rolled up to STIG IDs):

| System | ✅ Pass | ❌ Open | Agrees with OpenSCAP on |
| --- | ---: | ---: | --- |
| bootc server (srv01) | 285 | 112 | 253 of 346 findings |
| bootc workstation (ws01) | 279 | 118 | 246 of 344 |
| RPM server (rpm01) | 370 | 27 | 274 of 364 |

- **The 5 open on the bootc hosts are all explained in `controls.yaml`:** one
  AlmaLinux lab gap (a smart card package that only RHEL has), one proposed
  exception (boot loader superuser name), and three site settings (DNS servers,
  smart card certificate mapping, SELinux roles for sudo).
- **The RPM host's 104 open** are about half audit rules: 52 of the open
  findings, from 74 failing audit-rule checks. Lockdown writes those rules in a
  form Red Hat's checks don't accept. The rest are accounts and password
  settings (14 checks), sysctl (7), AIDE (5), SSSD (4) and smaller groups.
- **Each scanner favors the tool it was written for.** The Lockdown audit
  scores rpm01 best (27 open) and the bootc hosts worst (112 and 118). It's the
  mirror image of OpenSCAP. On srv01, 57 of the 121 failed Goss tests are audit
  rules. Goss greps Lockdown's own rule keys (`-k privileged-usermod`) in
  Lockdown's own file (`/etc/audit/rules.d/99_auditd.rules`). Red Hat's content
  loads the same rule under `key=privileged` in its own files, and `auditctl -l`
  on srv01 shows it in effect. Likewise, Goss reads sysctl settings only from
  `/etc/sysctl.d/`, so a value the OS ships in `/usr/lib/sysctl.d/` counts as
  open even when it's live (`accept_source_route = 0` on srv01). The findings
  both scanners call open (3 on srv01, 11 on rpm01) are the real gaps.
- **For the site:** keep one scanner as the scanner of record. Run the other
  only to look for blind spots, and read its "open" results as "check by hand",
  not as failures. OpenSCAP is the natural one of record for image mode: it scans
  the image before any host exists (`oscap-podman`), and it's Red Hat's content
  for Red Hat's OS.
- **rpm01 is stock Lockdown.** The site's RHEL 8 overrides weren't available to
  the lab, so rpm01 runs Lockdown's defaults plus the lab site values in
  `lab/lockdown/site-vars.yml`. Its scores describe the method, not the site's
  real configuration.
- **The last fixes reached the hosts without anyone touching them.** Fix in
  git → build → promote → `bootc upgrade` took srv01 from 10 open to 5.

## Consequences

- A STIG change is a code change: edit `controls.yaml` or the image, open a PR,
  and CI regenerates the tailoring and the finding map. The fix reaches hosts
  through the normal rebuild, promote and `bootc upgrade` path (see
  [day2.md](../day2.md)).
- A new DISA release means updating `scap-security-guide` in the mirror, then
  re-running `extract-ssg` and `make stig`. The finding map shows what changed.
- One build hardens every host the same way. Drift checks become "is this host
  running the approved image digest?" plus a periodic scan for `/etc` changes.
