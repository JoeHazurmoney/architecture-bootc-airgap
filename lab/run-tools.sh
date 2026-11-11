#!/bin/bash
# Run a command in the tools container on the lab PXE VM (rootless podman,
# host network so it can reach 10.77.0.0/24). The repo is mounted at /work.
#   lab/run-tools.sh ansible-playbook -i lab/inventory lab/playbooks/lab_site.yml
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
image="${BOOTC_TOOLS_IMAGE:-localhost/bootc-tools:latest}"

# ssh refuses keys that others can read (copies from Windows come over as 0644)
chmod 0600 "${repo}/lab/.lab-secrets/id_ed25519" 2>/dev/null || true

if ! podman image exists "${image}"; then
    podman build -f "${repo}/tools/Containerfile" -t "${image}" "${repo}"
fi

tty_flags=(-i)
[ -t 0 ] && [ -t 1 ] && tty_flags=(-it)

exec podman run --rm "${tty_flags[@]}" \
    --network host \
    --userns keep-id --user "$(id -u):$(id -g)" \
    -e HOME=/tmp -e ANSIBLE_CONFIG=/work/ansible/ansible.cfg \
    -e ANSIBLE_ROLES_PATH=/work/ansible/roles \
    -v "${repo}:/work:z" -w /work \
    "${image}" "$@"
