#!/usr/bin/env python3
"""Prepare media for the lab PXE server VM (run on the Windows Hyper-V host).

  py lab/prepare_pxe_vm.py

1. Creates the lab SSH key in lab/.lab-secrets/ (git-ignored) if missing.
2. Downloads the AlmaLinux 10 GenericCloud qcow2 and checks its SHA-256.
3. Renders cloud-init NoCloud seed files (user, SSH key, static lab IP).
4. In the tools container (Docker or Podman): converts the qcow2 to a dynamic
   VHDX and builds the CIDATA seed ISO.

Output: lab/.media/bootc-lab-pxe.vhdx and lab/.media/bootc-lab-pxe-seed.iso.
Next:   lab/hyperv/New-BootcLabPxeServer.ps1
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "lab"
SECRETS = LAB / ".lab-secrets"
MEDIA = LAB / ".media"
SEED = MEDIA / "seed"

CLOUD_BASE = "https://repo.almalinux.org/almalinux/10/cloud/x86_64/images/"
CLOUD_IMAGE = "AlmaLinux-10-GenericCloud-latest.x86_64.qcow2"
TOOLS_IMAGE = "localhost/bootc-tools:latest"

# Must match lab/hyperv/New-BootcLabPxeServer.ps1
UPLINK_MAC = "02:00:77:00:00:0a"
LAB_MAC = "02:00:77:00:00:10"
LAB_IP = "10.77.0.10/24"


def engine() -> str:
    for name in ("docker", "podman"):
        if shutil.which(name):
            return name
    sys.exit("Need docker or podman on PATH to run the tools container.")


def ensure_ssh_key() -> str:
    SECRETS.mkdir(parents=True, exist_ok=True)
    key = SECRETS / "id_ed25519"
    if not key.exists():
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "bootc-lab", "-f", str(key)],
            check=True,
        )
    return (SECRETS / "id_ed25519.pub").read_text().strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_cloud_image() -> Path:
    MEDIA.mkdir(parents=True, exist_ok=True)
    dest = MEDIA / CLOUD_IMAGE
    with urllib.request.urlopen(CLOUD_BASE + "CHECKSUM", timeout=60) as r:
        checksums = r.read().decode()
    expected = None
    for line in checksums.splitlines():
        if line.startswith(f"SHA256 ({CLOUD_IMAGE})"):          # BSD style
            expected = line.rsplit("=", 1)[1].strip()
        elif line.split()[-1:] == [CLOUD_IMAGE]:                  # sha256sum style
            expected = line.split()[0]
    if not expected:
        sys.exit(f"No SHA-256 for {CLOUD_IMAGE} in {CLOUD_BASE}CHECKSUM")
    if dest.exists() and sha256(dest) == expected:
        print(f"Cloud image already downloaded: {dest}")
        return dest
    print(f"Downloading {CLOUD_IMAGE} ...")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(CLOUD_BASE + CLOUD_IMAGE, timeout=60) as r, tmp.open("wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    actual = sha256(tmp)
    if actual != expected:
        tmp.unlink()
        sys.exit(f"Checksum mismatch for {CLOUD_IMAGE}: {actual} != {expected}")
    tmp.replace(dest)
    return dest


def write_seed(pubkey: str) -> None:
    SEED.mkdir(parents=True, exist_ok=True)
    (SEED / "meta-data").write_text(
        "instance-id: bootc-lab-pxe-001\nlocal-hostname: bootc-lab-pxe\n"
    )
    (SEED / "user-data").write_text(f"""#cloud-config
hostname: bootc-lab-pxe
users:
  - name: labadmin
    groups: [wheel]
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - {pubkey}
growpart:
  mode: auto
  devices: ["/"]
# hyperv-daemons: KVP reports the VM's IPs to Hyper-V (Get-VMNetworkAdapter)
packages: [hyperv-daemons, podman, rsync, tar, git]
runcmd:
  # hypervkvpd is udev-started; its rule arrived after boot, so re-trigger first
  - [udevadm, trigger, --subsystem-match=misc, --action=add]
  - [udevadm, settle]
  - [systemctl, start, hypervkvpd.service]
""")
    (SEED / "network-config").write_text(f"""version: 2
ethernets:
  uplink:
    match:
      macaddress: "{UPLINK_MAC}"
    dhcp4: true
  lab:
    match:
      macaddress: "{LAB_MAC}"
    dhcp4: false
    addresses: [{LAB_IP}]
""")


def build_media(cloud_image: Path) -> None:
    eng = engine()
    if subprocess.run([eng, "image", "inspect", TOOLS_IMAGE], capture_output=True).returncode != 0:
        subprocess.run([eng, "build", "-f", "tools/Containerfile", "-t", TOOLS_IMAGE, "."], cwd=ROOT, check=True)
    vhdx = "bootc-lab-pxe.vhdx"
    script = (
        f"rm -f {vhdx} bootc-lab-pxe-seed.iso && "
        f"qemu-img convert -p -O vhdx -o subformat=dynamic {cloud_image.name} {vhdx} && "
        "genisoimage -quiet -output bootc-lab-pxe-seed.iso -volid cidata -joliet -rock "
        "seed/user-data seed/meta-data seed/network-config"
    )
    subprocess.run(
        [eng, "run", "--rm", "-v", f"{MEDIA}:/media", "-w", "/media", TOOLS_IMAGE, "sh", "-c", script],
        check=True,
    )


def main() -> int:
    pubkey = ensure_ssh_key()
    image = download_cloud_image()
    write_seed(pubkey)
    build_media(image)
    print(f"\nReady:\n  {MEDIA / 'bootc-lab-pxe.vhdx'}\n  {MEDIA / 'bootc-lab-pxe-seed.iso'}")
    print("Next: powershell -File lab/hyperv/New-BootcLabNetwork.ps1; "
          "powershell -File lab/hyperv/New-BootcLabPxeServer.ps1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
