#!/usr/bin/env python3
"""Render the bootc_pxe output for every inventory and validate it.

Runs in the tools container (CI and local), never on a host Python:

    python3 tools/render_check.py                 # all inventories
    python3 tools/render_check.py lab/inventory   # just one

Checks:
  * every Kickstart parses with pykickstart's RHEL10 grammar, installs the OS
    with exactly one of ostreecontainer/bootc, and has no %packages section
  * nothing is left unrendered ("{{", "{%")
  * GRUB files have balanced braces and the menu entries we expect; grub.cfg
    sets its own prefix and never uses test -f on a network path
  * the Kea snippet is valid JSON
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from pykickstart.errors import KickstartError
from pykickstart.parser import KickstartParser
from pykickstart.version import RHEL10, makeVersion

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INVENTORIES = ["ansible/inventory/example", "lab/inventory"]
OUT = ROOT / "artifacts" / "render"


def render(inventory: str) -> Path:
    out = OUT / Path(inventory).as_posix().replace("/", "_")
    subprocess.run(
        [
            "ansible-playbook",
            "-i", str(ROOT / inventory),
            "playbooks/render_check.yml",
            "-e", f"bootc_pxe_render_dir={out}",
        ],
        cwd=ROOT / "ansible",
        check=True,
    )
    return out


def check_kickstart(path: Path) -> list[str]:
    errors = []
    text = path.read_text()
    parser = KickstartParser(makeVersion(RHEL10))
    try:
        parser.readKickstartFromString(text)
    except KickstartError as exc:
        errors.append(f"{path}: pykickstart: {exc}")
    commands = [ln.split()[0] for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    installers = [c for c in commands if c in ("ostreecontainer", "bootc")]
    if len(installers) != 1:
        errors.append(f"{path}: expected one ostreecontainer/bootc line, found {installers}")
    # Without --target-imgref, the installed host's update source is the
    # --source-imgref string, transport prefix and all, and `bootc upgrade` fails.
    for ln in text.splitlines():
        if ln.startswith("bootc "):
            target = re.search(r"--target-imgref=(\S+)", ln)
            if not target or re.match(r"[a-z-]+:(?!\d)", target.group(1)):
                errors.append(f"{path}: bootc needs --target-imgref without a transport prefix")
    if "%packages" in commands:
        errors.append(f"{path}: %packages is not allowed in an image-mode install")
    # A text-mode install makes Anaconda link /etc default.target to multi-user.target,
    # overriding the image (a workstation would never reach GDM). %post must undo it.
    if "rm -f /etc/systemd/system/default.target" not in text.split("%post", 1)[-1]:
        errors.append(f"{path}: %post must remove Anaconda's default.target so the image decides")
    return errors


def check_grub(path: Path) -> list[str]:
    text = path.read_text()
    errors = []
    if text.count("{") != text.count("}"):
        errors.append(f"{path}: unbalanced braces")
    # Signed GRUB's built-in prefix is (tftp,<server>)/EFI/BOOT, not the directory
    # it was loaded from, so the entry file must set it.
    if path.name.startswith("grub") and not re.search(r'^set prefix="\(\$\{root\}\)/\S+/EFI/BOOT"$', text, re.M):
        errors.append(f"{path}: grub.cfg must set prefix to its own TFTP/HTTP directory")
    # test -f/-e lists the parent directory, which GRUB can't do over TFTP/HTTP:
    # it is always false there and the file is never even requested.
    if re.search(r'\[[^]]*-[fe] "?\$\{prefix\}', text):
        errors.append(f"{path}: test -f/-e on ${{prefix}} is always false over the network")
    if path.name == "menu.cfg" and "--id local" not in text:
        errors.append(f"{path}: menu has no local-disk entry")
    if "/hosts/" in path.as_posix() and "--id install" not in text:
        errors.append(f"{path}: host file has no install entry")
    return errors


def main(argv: list[str]) -> int:
    inventories = argv or DEFAULT_INVENTORIES
    errors: list[str] = []
    counts = {"kickstart": 0, "grub": 0}
    for inv in inventories:
        out = render(inv)
        for f in sorted(p for p in out.rglob("*") if p.is_file()):
            text = f.read_text()
            if "{{" in text or "{%" in text:
                errors.append(f"{f}: unrendered Jinja")
            if f.suffix == ".ks":
                counts["kickstart"] += 1
                errors += check_kickstart(f)
            elif f.suffix == ".cfg" and "EFI" in f.parts:
                counts["grub"] += 1
                errors += check_grub(f)
            elif f.name.endswith(".json"):
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    errors.append(f"{f}: invalid JSON: {exc}")
    for e in errors:
        print(f"FAIL {e}")
    print(f"Checked {counts['kickstart']} kickstarts and {counts['grub']} GRUB files "
          f"from {len(inventories)} inventories: {'FAILED' if errors else 'OK'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
