# DISA STIG for image-mode hosts: overview for the ISSO team

This page explains, without assuming Linux expertise, how the new hosts meet
the **DISA Red Hat Enterprise Linux 10 STIG (Version 1, Release 2)** and where
to find the evidence for each finding.

| If you want to… | Open |
| --- | --- |
| See every finding, how it's met, and the scan result | [finding-map.md](finding-map.md) |
| Open the checklists in DISA STIG Viewer 3 | [checklists/](checklists/) (`.cklb` files, one per scanned system) |
| Follow a guided demo of a few findings end to end | [show-and-tell.md](show-and-tell.md) |
| Review the decisions and exceptions | [compliance/stig/controls.yaml](../../compliance/stig/controls.yaml) |
| Understand why we chose this approach | [trade-study.md](trade-study.md) |
| See the technical detail | [how-it-works.md](how-it-works.md) |

## What changed: the operating system is now built once, like a container

**Before:** each server or workstation was installed from packages, then
hardened on the host. Patches were installed host by host. Over time, hosts in
the same role drifted apart, and each one had to be scanned and fixed on its own.

**Now:** the operating system is a single **image**, built automatically from
files in a version-controlled repository (git).
- The STIG settings are applied **once, while the image is built**.
- The hardened image is scanned **before any host runs it**.
- Every host built from that image gets **identical** files.
- The system part of the disk is **read-only** on the running host, so it can't
  be changed there, accidentally or otherwise.
- A patch means building a new image, scanning it and rolling it out. A bad
  update can be rolled back in one step.

```text
  ┌───────────────┐   ┌──────────────────────┐   ┌───────────────┐   ┌───────────────┐   ┌────────────────┐
  │ git repository│──►│ automated image build│──►│ scan the image│──►│ install hosts │──►│ scan the hosts │
  │ settings and  │   │ applies Red Hat's    │   │ (before use)  │   │ disk layout,  │   │ + STIG Viewer  │
  │ decisions     │   │ STIG content         │   │               │   │ FIPS at setup │   │   checklists   │
  └───────────────┘   └──────────────────────┘   └───────────────┘   └───────────────┘   └────────────────┘
        ▲                                                                                        │
        └──────────── a finding is fixed in git, never by hand on a host ◄───────────────────────┘
```

## Where each finding is met

Every one of the 434 findings in the STIG has a row in
[finding-map.md](finding-map.md). The **How it's met** column is one of these:

| How it's met | What it means |
| --- | --- |
| **Image build (OpenSCAP)** | Applied automatically during the image build by Red Hat's own STIG content (the same content Red Hat Satellite and Red Hat Lightspeed use to scan). This covers the large majority of findings. |
| **Image file** | A specific settings file we wrote and ship in the image, named in the **Where** column. Used when the automated content can't do it during a build, such as turning on FIPS mode. |
| **Installer (Kickstart)** | Set when a host is installed, such as the separate disk areas for `/var`, `/var/log`, `/var/log/audit`, `/tmp`, `/var/tmp` and `/home`. |
| **Site setting** | Needs information only the site has (time servers, DNS servers, smart card certificate rules). The repository shows where it goes. |
| **Exception** | Not met as written. The reason and the approval status are recorded. These are the items for your review and the POA&M. |
| **Not applicable** | Doesn't apply to this kind of system, with the reason recorded. |
| **Manual / procedural** | Checked by a person or a process, not by a scan. |

## Reading the finding map

Each row shows:
- the DISA identifiers: **STIG ID** (e.g. `RHEL-10-000500`) and **V-ID** (e.g. `V-281009`)
- the requirement in short form
- how the finding is met
- **Where**: links to the exact file in the repository
- a result per scanned system:

| Symbol | Meaning |
| --- | --- |
| ✅ | **Not a Finding**: the automated check passed |
| ❌ | **Open**: the check failed. For an exception, this is expected and the reason is in the row. |
| ➖ | **Not Applicable** to that system |
| ⬜ | **Not Reviewed**: no automated result, or not scanned yet |

The scanned systems (columns) are:

| Column | What was scanned |
| --- | --- |
| Base img | The operating system image **before** the STIG layer: the starting point |
| Srv img / WS img | The hardened server and workstation images, scanned in the image registry before any host uses them |
| Srv host / WS host | A real server and a real workstation installed from those images |
| RPM host | A comparison server installed and hardened **the way RHEL 8 hosts are today**: a package install, then the Ansible Lockdown STIG role run against it |

The images and the hosts are both scanned because some checks can only be
answered on a running system: disk layout, mounted file systems, and the
running kernel's FIPS mode.

**Two independent scanners.** Every host is checked by two tools, and a host
cell shows both results as **OpenSCAP / Lockdown audit**, for example `✅/✅`:
- **OpenSCAP**, using Red Hat's STIG content: the scanner behind Red Hat
  Satellite and Red Hat Lightspeed.
- **The Ansible Lockdown audit**: the tool that checks today's RHEL 8 hosts.

Both are keyed by the same DISA STIG ID. Where they disagree, the summary
counts it, so you can see whether a pass depends on which tool you ask.

## The checklists

[checklists/](checklists/) has one `.cklb` file per scanned system. Open them in
**DISA STIG Viewer 3** (File → Open Checklist). Each finding carries:

- **Status**, from the scan, as described above
- **Finding Details**: which automated check(s) ran and their results
- **Comments**: how the finding is met, where in the repository, and for
  exceptions the justification and approval status

The checklists are generated from DISA's own STIG file plus the scan results,
so DISA's check and fix text appears unchanged.

## How exceptions get approved

1. An engineer proposes the exception in
   [compliance/stig/controls.yaml](../../compliance/stig/controls.yaml), with a
   plain-language reason and `approval: proposed`.
2. The change goes through a **pull request**. The ISSO reviews it there and
   can comment or request changes.
3. On approval, the entry is updated to, for example,
   `approval: approved 2026-12-01 (ticket ABC-123)`. The finding map and the
   checklists pick this up automatically.

The pull request history is the audit trail: who proposed what, who approved
it, and when.

## The lab and the real thing

The examples here were produced in an isolated lab that uses **AlmaLinux 10**,
a free rebuild of Red Hat Enterprise Linux 10, with the same STIG content.
On real RHEL 10 the results are expected to match, except that FIPS mode is
**validated** only on RHEL. See [how-it-works.md](how-it-works.md#rhel-vs-the-almalinux-lab).
