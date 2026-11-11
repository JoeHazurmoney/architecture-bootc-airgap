#!/bin/bash
# Run a command in the tools container on the lab PXE VM (rootless podman,
# host network so it can reach 10.77.0.0/24). The repo is mounted at /work.
#   lab/run-tools.sh ansible-playbook -i lab/inventory lab/playbooks/lab_site.yml
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
image="${BOOTC_TOOLS_IMAGE:-localhost/bootc-tools:latest}"

if ! podman image exists "${image}"; then
    podman build -f "${repo}/tools/Containerfile" -t "${image}" "${repo}"
fi

exec podman run --rm -it \
    --network host \
    --userns keep-id --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e ANSIBLE_CONFIG=/work/ansible/ansible.cfg \
    -e ANSIBLE_ROLES_PATH=/work/ansible/roles \
    -v "${repo}:/work:z" -w /work \
    "${image}" "$@"
