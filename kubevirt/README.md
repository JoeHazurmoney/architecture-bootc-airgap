# KubeVirt / OpenShift Virtualization manifests (plain YAML)

These do the same thing as the `bootc_kubevirt_image` role, for teams that use
`oc apply` or GitOps (Argo CD) instead of Ansible. Replace the `<...>`
placeholders before you apply them.

| File | What it does |
| --- | --- |
| `datavolume.example.yaml` | Imports the bootc qcow2 (HTTP or containerDisk) into a PVC |
| `datasource.example.yaml` | The stable "golden image" name VMs clone from |
| `virtualmachine.example.yaml` | A VM cloned from the DataSource, with cloud-init Day-1 settings |

Flow for each new image version:

1. `bootc_image_build` with `bootc_build_action=disk` turns `bootc/server:<version>` into `disk.qcow2`.
2. Publish the disk:
   - put it on the HTTP server, or
   - wrap it as a containerDisk (`images/containerdisk/Containerfile`) and push it to the registry.
3. Apply a new versioned DataVolume, then point the DataSource at it.
4. New VMs clone the new version. **Existing VMs don't need re-cloning**: they
   follow the registry tag with `bootc upgrade` (see `docs/day2.md`), the same
   as bare metal.
