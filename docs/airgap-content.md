# What to carry into the airgap

Everything below crosses the airgap through your normal transfer process
(oc-mirror archive, removable media, diode). Inside, it all comes from the
internal registry and internal repo mirrors.

| Content | Source (connected side) | Destination (inside) | Used by |
| --- | --- | --- | --- |
| bootc base image | `registry.redhat.io/rhel10/rhel-bootc:10.x` | `<registry>/rhel10/rhel-bootc:10.x` | `image_patch.yml` (`bootc_build_base_image`) |
| bootc-image-builder | `registry.redhat.io/rhel10/bootc-image-builder:10.x` | `<registry>/rhel10/bootc-image-builder:10.x` | `image_disk.yml` (`bootc_build_bib_image`) |
| RHEL 10 boot ISO | `rhel-10.x-x86_64-boot.iso` from the Customer Portal | PXE host, `bootc_pxe_iso_path` | `bootc_pxe` (kernel, initrd, stage2, shim, GRUB) |
| RPM repos for image builds | BaseOS + AppStream (and EPEL if you use `lldpd`) | Satellite / Pulp / reposync mirror → `images/repos/*.repo` | Containerfile `dnf install` and `APPLY_UPDATES=true` |
| Tools container base | `docker.io/library/python:3.14.10-slim` (pinned digest) + PyPI wheels + Galaxy collections | build it on the connected side and transfer it, or mirror PyPI/Galaxy | `make` targets, control node |
| Registry CA | your PKI | `ansible/inventory/<site>/files/registry-ca.crt` | baked into images; installer `%pre` |

## Mirroring the images

With `oc-mirror` (you probably run it for OCP already), add to the
`ImageSetConfiguration`:

```yaml
mirror:
  additionalImages:
    - name: registry.redhat.io/rhel10/rhel-bootc:10.2
    - name: registry.redhat.io/rhel10/bootc-image-builder:10.2
```

Or with `skopeo` (connected side → archive → inside):

```bash
skopeo copy --override-arch amd64 docker://registry.redhat.io/rhel10/rhel-bootc:10.2 \
  oci-archive:rhel-bootc-10.2.tar
# inside:
skopeo copy oci-archive:rhel-bootc-10.2.tar docker://registry.internal:8443/rhel10/rhel-bootc:10.2
```

Mirror by **dated tag or digest**, not only the floating `10.2` tag, so a
rebuild is reproducible and the RPM diff in `image_patch.yml` means something.

## The boot ISO

The installer (Anaconda) does the `ostreecontainer` pull, so the **boot ISO's
minor version should be at least the image's**. Use the 10.2 boot ISO for 10.2
images. The `bootc` Kickstart command needs a 10.2+ installer;
`ostreecontainer` works from 10.0.

Copy the ISO to the PXE host and set `bootc_pxe_installer_release` (e.g.
`"10.2"`). Several releases can sit side by side under
`/var/www/bootc/installer/<release>/`.
