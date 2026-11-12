# STIG show-and-tell: seven findings, end to end

A demo script for the ISSO team, about 30 minutes. Each finding follows the
same path:

> **requirement → where it lives in git → scan of the image → scan of a running
> host → the same finding on today's RPM + Lockdown host → what happens if
> someone changes it**

Have these open:
- [finding-map.md](finding-map.md): every finding, one row each
- a checklist from [checklists/](checklists/) in STIG Viewer 3 (`server-host.cklb`)
- the HTML scan reports from `artifacts/stig/<date>/`, for the detail behind any row
- an SSH session to `bootc-lab-srv01` and `bootc-lab-rpm01`, from the PXE VM

The IDs below are DISA's: **STIG ID** (`RHEL-10-…`) and **V-ID** (`V-…`), as
shown in STIG Viewer.

---

## 0. The big picture (3 minutes)

Show the summary table at the top of [finding-map.md](finding-map.md). Points to make:
- **All 434 findings have a row and a disposition.** Nothing is unaccounted for. CI fails if one is ever missing.
- **Most findings are met by Red Hat's own STIG content** applied while the image is built ("Image build (OpenSCAP)"). That's the same content Red Hat Satellite and Lightspeed scan with.
- **Compare the targets.** The plain image, then the hardened image, then the running bootc host, then today's RPM + Lockdown host. The hardened image is scanned *before* any host runs it.
- **The handful of exceptions and site settings are listed by name**, with reasons. Those are the decisions that need the ISSO.

## 1. FIPS mode: RHEL-10-000500 (V-281009), CAT I

**Requirement, in plain words:** the system must use only FIPS-validated cryptography.

**Where it lives:** two places, because FIPS has to be on from the very first boot.
- [01-fips.toml](../../images/stig/rootfs/usr/lib/bootc/kargs.d/01-fips.toml):
  one line, `kargs = ["fips=1"]`. Every host built from the image boots in FIPS
  mode, including after every update.
- The installer itself boots with `fips=1` (`stig: true` in
  `bootc_pxe_images`), so the keys created during install (SSH host keys) are
  FIPS-generated.

**Show it on srv01:**

```bash
cat /proc/sys/crypto/fips_enabled     # 1
update-crypto-policies --show         # FIPS
```

**Story to tell:** turning FIPS on broke the lab's SSH login. FIPS mode refuses
Ed25519 keys, so the admin keys had to change to ECDSA. Finding that once, in a
lab, beats finding it during a production cutover.

## 2. No root login over SSH: RHEL-10-700620 (V-281265)

**Requirement:** nobody may log in directly as `root` over SSH.

**Where it lives:** applied by Red Hat's STIG content during the image build
("Image build (OpenSCAP)"). There is no hand-written file for it; the scan
proves it's there.

**Show it:** the row in the finding map is ✅ for the hardened image, srv01 and
ws01. Then, on srv01:

```bash
sudo sshd -T | grep -i permitrootlogin     # permitrootlogin no
```

**What if someone changes it?** On srv01, an admin edits `/etc/ssh/sshd_config`
and sets `PermitRootLogin yes`.
- The next host scan marks the row ❌ Open.
- `/etc` is the one place a bootc host can drift. `/usr` (the OS itself) is read-only.
- The fix is never "edit it back by hand". You restore the image's file, or roll the host back to the approved image (`bootc rollback`).
- Show that `/usr` really is read-only: `sudo touch /usr/bin/x` gives "Read-only file system".

## 3. Separate file system for audit records: RHEL-10-000520 (V-280936)

**Requirement:** audit logs live on their own disk volume, so a full disk
elsewhere can't stop auditing.

**Where it lives:** the installer. A container image can't partition a disk. The
STIG disk layout is `bootc_pxe_partitioning_stig` in
[bootc_pxe defaults](../../ansible/roles/bootc_pxe/defaults/main.yml), used for
every image marked `stig: true`.

**Show it on srv01:**

```bash
findmnt /var/log/audit      # its own volume, nodev,nosuid,noexec
```

**Story to tell:** the newer `bootc` installer command can't create these
volumes yet. The lab found that, and the tooling now refuses that combination
for STIG installs.

## 4. Login banner over SSH: RHEL-10-700010 (V-281224)

**Requirement:** show the Standard Mandatory DoD Notice and Consent Banner
before login.

**Where it lives:** image build (OpenSCAP), with the DoD text from the STIG content.

**Show it:** start an SSH session to srv01; the banner appears before the
password or key prompt.

## 5. Application allow-listing: RHEL-10-200602 (V-280971)

**Requirement:** only authorized software may run (deny-all, permit-by-exception).

**Where it lives:** image build (OpenSCAP) installs and enables `fapolicyd`
with a deny-by-default policy. It trusts what the RPM database lists.

**Story to tell:** in image mode the OS itself *is* the approved software
list. It's whatever the scanned image contains, and nothing can be added to
`/usr` on the host. fapolicyd adds a second layer for anything dropped into
writable places like `/var` or `/home`.

## 6. USB device policy: RHEL-10-200562 (V-280964), a decision for the ISSO

**Requirement:** USBGuard must have a policy of authorized devices.

**Where it lives:** a file we wrote,
[rules.conf](../../images/stig/rootfs/etc/usbguard/rules.conf). It allows USB
hubs, keyboards and mice, and smart card readers (CAC/PIV). Everything else,
including USB storage, is blocked.

**Why it's a decision:** generating the policy automatically during the image
build would see no devices at all, and would lock every keyboard out of every
physical workstation. The row in `controls.yaml` is marked
`approval: proposed`, waiting for the ISSO to confirm the device list.

## 7. Disk encryption: RHEL-10-000510 (V-280935), CAT I, an exception

**Requirement:** encrypt data at rest on local disks.

**Status:** **Exception, proposed.** Zero-touch installs and unattended
reboots after updates need the disk to unlock without a person typing a
passphrase. The production plan is LUKS2 unlocked by the server's TPM chip
(Clevis) or by Tang servers on the management network. The Hyper-V lab
clients have no virtual TPM, so the lab doesn't encrypt.

**Show it:** the row is ❌ Open in every column, and the comment in the
checklist carries the justification and the approval status. **This is what an
honest exception looks like:** visible, explained, and tracked in git.

---

## Close (2 minutes): how a STIG change happens from now on

1. Someone proposes the change in `compliance/stig/controls.yaml`, or in the image, through a pull request.
2. The ISSO reviews the pull request. CI regenerates the finding map and the checklists, and fails if anything is unaccounted for.
3. After merge: build the image, scan it, promote it, and hosts update with `bootc upgrade`.
4. The git history is the audit trail: who changed what, who approved it, and when.
