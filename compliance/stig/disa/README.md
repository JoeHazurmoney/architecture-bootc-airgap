# DISA STIG source

`U_RHEL_10_STIG_V1R2_Manual-xccdf.xml` is DISA's *Red Hat Enterprise Linux 10
Security Technical Implementation Guide*, Version 1 Release 2 (benchmark date
01 Jul 2026). It's unmodified, extracted from DISA's public download:

- URL: <https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_RHEL_10_V1R2_STIG.zip>
- zip sha256: `d050b93c00d3c2cf8b0adec4a852f27bd827720cc4510ce32f3368006ad63ac3`
- xml sha256: `91327cd50ab0b4041463a9a1bdaf9b7c365576d67b6ed9864ab99b002bb33ae1`

It's the authoritative list of findings (V-ID, STIG ID, severity, check and fix
text) that `tools/stig_report.py` builds the finding map and the checklists
from. To move to a new release, replace the file, update `disa:` in
`../controls.yaml`, and run `make stig`.
