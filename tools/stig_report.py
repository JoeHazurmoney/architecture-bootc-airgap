#!/usr/bin/env python3
"""STIG finding map: DISA findings -> how we meet them -> scan evidence.

Runs in the tools container (CI and local), never on a host Python.

Inputs (all in git):
  compliance/stig/controls.yaml         what we decided, per DISA STIG ID (human-reviewed)
  compliance/stig/disa/*-xccdf.xml      DISA's finding list (V-ID, STIG ID, CAT, check/fix text)
  compliance/stig/ssg/<product>.json    OpenSCAP content: rule -> STIG IDs, profile selections
  compliance/stig/results/<target>.json scan results per target (image, hosts), OpenSCAP
  compliance/stig/results/<target>.lockdown.json  same targets, Ansible Lockdown audit (Goss)

Outputs:
  images/stig/tailoring.xml             OpenSCAP tailoring the image build uses
  docs/stig/finding-map.md              every DISA finding, how it's met, results per target
  docs/stig/checklists/<target>.cklb    STIG Viewer 3 checklists

Commands:
  extract-ssg <datastream-or-arf.xml>                 refresh compliance/stig/ssg/<product>.json
  results <arf.xml> --target NAME                     store one OpenSCAP scan's rule results
  results-goss <goss.json> --target NAME              store one Lockdown audit (Goss) run, per STIG ID
  generate                                            write tailoring.xml, finding-map.md, checklists
  check                                               fail if anything generated is stale or invalid
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STIG = ROOT / "compliance" / "stig"
CONTROLS = STIG / "controls.yaml"
TAILORING = ROOT / "images" / "stig" / "tailoring.xml"
FINDING_MAP = ROOT / "docs" / "stig" / "finding-map.md"
CHECKLISTS = ROOT / "docs" / "stig" / "checklists"

X11 = "http://checklists.nist.gov/xccdf/1.1"
X12 = "http://checklists.nist.gov/xccdf/1.2"
SSG_RULE = "xccdf_org.ssgproject.content_rule_"
SSG_PROFILE = "xccdf_org.ssgproject.content_profile_"
SSG_VALUE = "xccdf_org.ssgproject.content_value_"
# DISA STIG IDs ("RHEL-10-000500"). SSG also references the DISA rule ID (SV-…)
# and V-ID under similar hrefs, so match the ID's shape, not the link.
STIG_ID_RE = re.compile(r"^[A-Z0-9]+-\d{2}-\d{6}$")
UUID_NS = uuid.UUID("6f0d3c52-8f0b-4d63-9a43-4d4f2bb7a0a1")

DISPOSITIONS = {
    # key: (short label for tables, plain-language meaning)
    "image-openscap": ("Image build (OpenSCAP)", "Applied automatically when the image is built, by OpenSCAP's image-mode tool (oscap-im) running Red Hat's STIG content."),
    "image-file": ("Image file", "A configuration file we ship in the image (named in 'Where')."),
    "install-kickstart": ("Installer (Kickstart)", "Set when the host is installed, by the PXE Kickstart template."),
    "install-bib": ("VM disk template", "Set when the VM disk is built (bootc-image-builder config)."),
    "site-config": ("Site setting", "Needs a value only the site can give (servers, names, keys). The repo shows where it goes."),
    "exception": ("Exception", "Not met as written. The justification and approval status are recorded here."),
    "not-applicable": ("Not applicable", "Does not apply to this system type, with the reason recorded."),
    "manual-procedural": ("Manual / procedural", "A person or a process checks this. Any automated result is shown for reference only."),
}
STATUS_LABEL = {
    "not_a_finding": "✅ Pass",
    "open": "❌ Open",
    "not_applicable": "➖ N/A",
    "not_reviewed": "⬜ Not reviewed",
}


# --------------------------------------------------------------------------- inputs
def load_controls() -> dict:
    data = yaml.safe_load(CONTROLS.read_text(encoding="utf-8"))
    data.setdefault("findings", {})
    for sid, entry in data["findings"].items():
        entry.setdefault("where", [])
        entry.setdefault("deselect", [])
        entry.setdefault("values", {})
        entry.setdefault("profiles", list(data["profiles"]))
    return data


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load_disa(path: Path) -> dict:
    """DISA manual XCCDF (1.1) -> benchmark metadata + findings keyed by STIG ID."""
    root = ET.parse(path).getroot()
    ns = {"x": X11}
    release = " ".join(p.text or "" for p in root.findall("x:plain-text", ns) if p.get("id") == "release-info")
    bench = {
        "id": root.get("id"),
        "title": root.findtext("x:title", namespaces=ns),
        "version": root.findtext("x:version", namespaces=ns),
        "release_info": release,
    }
    findings = {}
    for group in root.findall("x:Group", ns):
        rule = group.find("x:Rule", ns)
        desc = rule.findtext("x:description", default="", namespaces=ns)
        m = re.search(r"<VulnDiscussion>(.*?)</VulnDiscussion>", desc, re.S)
        check = rule.find("x:check/x:check-content", ns)
        stig_id = rule.findtext("x:version", namespaces=ns)
        findings[stig_id] = {
            "stig_id": stig_id,
            "vuln_id": group.get("id"),
            "group_title": group.findtext("x:title", namespaces=ns),
            "rule_id": rule.get("id"),
            "severity": rule.get("severity"),
            "weight": rule.get("weight", "10.0"),
            "title": rule.findtext("x:title", namespaces=ns),
            "discussion": html.unescape(m.group(1)).strip() if m else "",
            "check": (check.text or "").strip() if check is not None else "",
            "fix": (rule.findtext("x:fixtext", default="", namespaces=ns) or "").strip(),
            "ccis": [i.text for i in rule.findall("x:ident", ns) if "cci" in (i.get("system") or "").lower()],
            "legacy": [i.text for i in rule.findall("x:ident", ns) if "legacy" in (i.get("system") or "").lower()],
        }
    return {"benchmark": bench, "findings": findings}


def load_ssg(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_results(name: str) -> dict | None:
    path = STIG / "results" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_lockdown(name: str) -> dict | None:
    path = STIG / "results" / f"{name}.lockdown.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --------------------------------------------------------------------------- extract
def find_benchmark(path: Path) -> ET.Element:
    """The XCCDF 1.2 Benchmark inside a source data stream or an ARF."""
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == f"{{{X12}}}Benchmark":
            return el
    raise SystemExit(f"{path}: no XCCDF 1.2 Benchmark found")


def cmd_extract_ssg(args: argparse.Namespace) -> None:
    bench = find_benchmark(Path(args.datastream))
    product = bench.get("id").replace("xccdf_org.ssgproject.content_benchmark_", "").lower().replace("-", "")
    rules = {}
    for rule in bench.iter(f"{{{X12}}}Rule"):
        rid = rule.get("id").removeprefix(SSG_RULE)
        refs = {(ref.text or "").strip() for ref in rule.findall(f"{{{X12}}}reference")}
        stig_ids = sorted(r for r in refs if STIG_ID_RE.match(r))
        if not stig_ids:
            continue
        fixes = {f.get("system") for f in rule.findall(f"{{{X12}}}fix")}
        rules[rid] = {
            "title": (rule.findtext(f"{{{X12}}}title") or "").strip(),
            "severity": rule.get("severity"),
            "stig_ids": stig_ids,
            "bootc_fix": "urn:xccdf:fix:script:bootc" in fixes,
        }
    profiles = {}
    for prof in bench.findall(f"{{{X12}}}Profile"):
        pid = prof.get("id").removeprefix(SSG_PROFILE)
        if pid in ("stig", "stig_gui"):
            profiles[pid] = {
                "title": prof.findtext(f"{{{X12}}}title"),
                "rules": sorted(s.get("idref").removeprefix(SSG_RULE)
                                for s in prof.findall(f"{{{X12}}}select") if s.get("selected") == "true"
                                and s.get("idref").startswith(SSG_RULE)),
            }
    out = {
        "product": product,
        "ssg_version": bench.findtext(f"{{{X12}}}version"),
        "profiles": profiles,
        "rules": dict(sorted(rules.items())),
    }
    dest = STIG / "ssg" / f"{product}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}: {len(rules)} rules with STIG IDs, profiles {sorted(profiles)}")


def cmd_results(args: argparse.Namespace) -> None:
    """Keep only what the report needs from a (30 MB) ARF: one result per rule."""
    results, meta = {}, {}
    for _, el in ET.iterparse(args.arf, events=("end",)):
        tag = strip_ns(el.tag)
        if tag == "rule-result" and el.get("idref", "").startswith(SSG_RULE):
            results[el.get("idref").removeprefix(SSG_RULE)] = el.findtext(f"{{{X12}}}result")
            el.clear()
        elif tag == "TestResult":
            meta = {
                "start": el.get("start-time"),
                "end": el.get("end-time"),
                "profile": (el.find(f"{{{X12}}}profile").get("idref") if el.find(f"{{{X12}}}profile") is not None else ""),
                "target": el.findtext(f"{{{X12}}}target"),
                "score": el.findtext(f"{{{X12}}}score"),
            }
        elif tag == "Benchmark":
            el.clear()
    if not results:
        raise SystemExit(f"{args.arf}: no rule results")
    counts = Counter(results.values())
    out = {"target": args.target, "description": args.description or "", **meta,
           "counts": dict(sorted(counts.items())), "rules": dict(sorted(results.items()))}
    dest = STIG / "results" / f"{args.target}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}: {dict(counts)}")


def cmd_results_goss(args: argparse.Namespace) -> None:
    """Ansible Lockdown audit (Goss JSON): every test carries meta.STIG_ID."""
    data = json.loads(Path(args.goss).read_text(encoding="utf-8"))
    per = defaultdict(list)
    meta = {}
    for r in data.get("results", []):
        m = r.get("meta") or {}
        if r.get("title") == "Benchmark MetaData":
            meta = {k: m.get(k) for k in ("benchmark_version", "host_hostname", "host_epoch", "host_os_release")}
            continue
        sid = m.get("STIG_ID")
        if not sid:
            continue
        per[sid].append("skipped" if r.get("skipped") else ("pass" if r.get("successful") else "fail"))
    findings = {}
    for sid, res in sorted(per.items()):
        if "fail" in res:
            st = "open"
        elif "pass" in res:
            st = "not_a_finding"
        else:
            st = "not_reviewed"
        findings[sid] = {"status": st, "tests": len(res), "failed": res.count("fail")}
    when = ""
    if meta.get("host_epoch"):
        when = dt.datetime.fromtimestamp(int(meta["host_epoch"]), dt.timezone.utc).isoformat(timespec="seconds")
    out = {"target": args.target, "tool": "Ansible Lockdown RHEL10-STIG-Audit (Goss)", "start": when, **meta,
           "counts": dict(sorted(Counter(f["status"] for f in findings.values()).items())),
           "findings": findings}
    dest = STIG / "results" / f"{args.target}.lockdown.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {dest.relative_to(ROOT)}: {out['counts']}")


# --------------------------------------------------------------------------- model
def build_model(controls: dict) -> dict:
    disa = load_disa(ROOT / controls["disa"]["xccdf"])
    ssg = load_ssg(ROOT / controls["ssg"]["map"])
    by_stig = defaultdict(list)
    for rid, rule in ssg["rules"].items():
        for sid in rule["stig_ids"]:
            by_stig[sid].append(rid)

    # Tailored profile = SSG profile minus deselects from controls.yaml
    tailored = {}
    for pname, pdef in controls["profiles"].items():
        rules = set(ssg["profiles"][pdef["base"]]["rules"])
        for sid, entry in controls["findings"].items():
            if pname in entry["profiles"]:
                rules -= set(entry["deselect"])
        tailored[pname] = rules

    rows = []
    for sid, f in sorted(disa["findings"].items(), key=lambda kv: (kv[1]["severity"] != "high", kv[1]["severity"] != "medium", kv[0])):
        entry = controls["findings"].get(sid, {})
        rules = sorted(by_stig.get(sid, []))
        selected = sorted({r for r in rules for p in tailored.values() if r in p})
        if entry.get("disposition"):
            disp = entry["disposition"]
        elif selected:
            disp = "image-openscap"
        else:
            disp = "manual-procedural"
        where = list(entry.get("where", []))
        if disp == "image-openscap" and not where:
            where = ["images/stig/Containerfile"]
        rows.append({**f, "rules": rules, "selected": selected, "disposition": disp,
                     "where": where, "note": entry.get("note", ""), "approval": entry.get("approval", "")})
    return {"disa": disa, "ssg": ssg, "tailored": tailored, "rows": rows}


def lockdown_status(row: dict, ld: dict) -> str:
    if row["disposition"] == "not-applicable":
        return "not_applicable"
    f = ld["findings"].get(row["stig_id"])
    return f["status"] if f else "not_reviewed"


def status_for(row: dict, target: dict, results: dict | None, tailored: set) -> tuple[str, str]:
    """(CKLB status, finding details) for one finding on one target."""
    if row["disposition"] == "not-applicable":
        return "not_applicable", f"Not applicable: {row['note']}"
    manual = row["disposition"] == "manual-procedural"
    rules = [r for r in row["rules"] if r in tailored]
    if results is None:
        return "not_reviewed", "No scan results for this target yet."
    seen = {r: results["rules"].get(r) for r in rules if results["rules"].get(r)}
    if not seen:
        why = "No automated check selected for this finding." if not rules else "Not evaluated in this scan."
        return "not_reviewed", why
    vals = set(seen.values())
    detail = "; ".join(f"{r}: {v}" for r, v in sorted(seen.items()))
    if vals & {"fail", "error"}:
        st = "open"
    elif vals & {"notchecked", "unknown"}:
        st = "not_reviewed"
    elif vals <= {"notapplicable", "notselected"}:
        st = "not_applicable"
    else:
        st = "not_a_finding"
    if manual:
        # A person verifies these; the automated result is shown for reference only
        return "not_reviewed", f"Manual check. OpenSCAP result for reference: {detail}"
    return st, f"OpenSCAP ({results.get('start', '')[:10]}, {target['label']}): {detail}"


# --------------------------------------------------------------------------- outputs
def render_tailoring(controls: dict, model: dict) -> str:
    T = "xccdf-1.2"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- GENERATED by tools/stig_report.py from compliance/stig/controls.yaml. Do not edit. -->",
        f'<{T}:Tailoring xmlns:{T}="{X12}" id="xccdf_io.github.bootc-airgap_tailoring_stig">',
        f'  <{T}:benchmark href="/usr/share/xml/scap/ssg/content/ssg-{model["ssg"]["product"]}-ds.xml"/>',
        f'  <{T}:version time="{controls["tailoring_version"]}T00:00:00">{controls["tailoring_version"]}</{T}:version>',
    ]
    for pname, pdef in controls["profiles"].items():
        base = pdef["base"]
        lines.append(f'  <{T}:Profile id="{SSG_PROFILE}{base}_site" extends="{SSG_PROFILE}{base}">')
        lines.append(f"    <{T}:title>{html.escape(pdef['title'])}</{T}:title>")
        lines.append(f"    <{T}:description>Site tailoring of the DISA STIG profile for the {pname} image. "
                     f"Every change below is justified in compliance/stig/controls.yaml.</{T}:description>")
        for sid, entry in sorted(controls["findings"].items()):
            if pname not in entry["profiles"]:
                continue
            for rid in entry["deselect"]:
                lines.append(f'    <{T}:select idref="{SSG_RULE}{rid}" selected="false"/><!-- {sid} -->')
            for var, val in entry["values"].items():
                lines.append(f'    <{T}:set-value idref="{SSG_VALUE}{var}">{html.escape(str(val))}</{T}:set-value><!-- {sid} -->')
        lines.append(f"  </{T}:Profile>")
    lines.append(f"</{T}:Tailoring>")
    return "\n".join(lines) + "\n"


def md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def link(path: str) -> str:
    return f"[{Path(path).name}](../../{path})"


def render_finding_map(controls: dict, model: dict) -> str:
    targets = controls["targets"]
    results = {t["name"]: load_results(t["name"]) for t in targets}
    bench = model["disa"]["benchmark"]
    rows = model["rows"]
    out = [
        "<!-- GENERATED by tools/stig_report.py. Edit compliance/stig/controls.yaml, then run `make stig`. -->",
        "# STIG finding map",
        "",
        f"Every finding in the **{bench['title']}** (Version {bench['version']}, {bench['release_info'].strip()}), "
        f"how this repo meets it, and what the scans found. SCAP content: scap-security-guide "
        f"{model['ssg']['ssg_version']} ({model['ssg']['product']}).",
        "",
        "How to read it: [README.md](README.md#reading-the-finding-map). Each finding's full DISA text is in the checklists "
        "under [checklists/](checklists/), which open in DISA STIG Viewer 3.",
        "",
        "## Summary",
        "",
        "| How it's met | CAT I | CAT II | CAT III | Total |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    cat = {"high": "CAT I", "medium": "CAT II", "low": "CAT III"}
    by = Counter((r["disposition"], r["severity"]) for r in rows)
    for key, (label, _) in DISPOSITIONS.items():
        n = [by[(key, s)] for s in ("high", "medium", "low")]
        if sum(n):
            out.append(f"| {label} | {n[0]} | {n[1]} | {n[2]} | {sum(n)} |")
    out.append(f"| **All findings** | {sum(r['severity'] == 'high' for r in rows)} | "
               f"{sum(r['severity'] == 'medium' for r in rows)} | {sum(r['severity'] == 'low' for r in rows)} | {len(rows)} |")
    out += ["", "### Scan results by target", "",
            "Two independent scanners, both keyed by DISA STIG ID: **OpenSCAP** with Red Hat's STIG content "
            "(images and hosts), and the **Ansible Lockdown audit** (Goss, the site's current tool; running hosts only).",
            "",
            "| Target | Scanner | Scanned | " + " | ".join(STATUS_LABEL.values()) + " |",
            "| --- | --- | --- | " + " | ".join("---:" for _ in STATUS_LABEL) + " |"]
    statuses, lockdown = {}, {}
    for t in targets:
        tail = model["tailored"][t["profile"]]
        statuses[t["name"]] = [status_for(r, t, results[t["name"]], tail)[0] for r in rows]
        c = Counter(statuses[t["name"]])
        when = (results[t["name"]] or {}).get("start", "")[:10] or "not yet"
        out.append(f"| {t['label']} | OpenSCAP | {when} | " + " | ".join(str(c[s]) for s in STATUS_LABEL) + " |")
        ld = load_lockdown(t["name"])
        if ld is not None:
            lockdown[t["name"]] = [lockdown_status(r, ld) for r in rows]
            c = Counter(lockdown[t["name"]])
            out.append(f"| {t['label']} | Lockdown audit | {ld.get('start', '')[:10]} | "
                       + " | ".join(str(c[s]) for s in STATUS_LABEL) + " |")
    if lockdown:
        out += ["", "Where both scanners ran, how often they agree (ignoring not-reviewed and N/A):", "",
                "| Target | Both pass | Both open | Only OpenSCAP open | Only Lockdown open |",
                "| --- | ---: | ---: | ---: | ---: |"]
        for t in targets:
            if t["name"] not in lockdown:
                continue
            pairs = Counter(zip(statuses[t["name"]], lockdown[t["name"]]))
            out.append(f"| {t['label']} | {pairs[('not_a_finding', 'not_a_finding')]} | {pairs[('open', 'open')]} | "
                       f"{pairs[('open', 'not_a_finding')]} | {pairs[('not_a_finding', 'open')]} |")
    out += ["", "Targets: " + "; ".join(f"**{t['label']}**: {t['description']}" for t in targets), "",
            "In the tables below, a host cell shows **OpenSCAP / Lockdown audit** where both scanners ran.", ""]
    out += ["## Dispositions", ""]
    out += [f"- **{label}**: {meaning}" for label, meaning in DISPOSITIONS.values()]
    for sev in ("high", "medium", "low"):
        sel = [(i, r) for i, r in enumerate(rows) if r["severity"] == sev]
        if not sel:
            continue
        out += ["", f"## {cat[sev]} ({len(sel)} findings)", "",
                "| STIG ID | V-ID | Requirement | How it's met | Where | " + " | ".join(t["short"] for t in targets) + " |",
                "| --- | --- | --- | --- | --- | " + " | ".join("---" for _ in targets) + " |"]
        for i, r in sel:
            req = re.sub(r"^RHEL 10 must (be configured (so that|to) )?", "", r["title"]).rstrip(".")
            req = req[:1].upper() + req[1:]
            how = DISPOSITIONS[r["disposition"]][0]
            if r["note"]:
                how += f" — {r['note']}"
            if r["approval"]:
                how += f" (approval: {r['approval']})"
            where = ", ".join(link(w) for w in r["where"])
            cells = [STATUS_LABEL[statuses[t["name"]][i]].split(" ")[0]
                     + (("/" + STATUS_LABEL[lockdown[t["name"]][i]].split(" ")[0]) if t["name"] in lockdown else "")
                     for t in targets]
            out.append(f"| {r['stig_id']} | {r['vuln_id']} | {md_cell(req)} | {md_cell(how)} | {where} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def render_cklb(controls: dict, model: dict, target: dict) -> str:
    results = load_results(target["name"])
    ld = load_lockdown(target["name"])
    tail = model["tailored"][target["profile"]]
    bench = model["disa"]["benchmark"]
    stig_uuid = str(uuid.uuid5(UUID_NS, f"{bench['id']}-{bench['version']}-{target['name']}"))
    rules = []
    for r in sorted(model["rows"], key=lambda r: r["vuln_id"]):
        status, details = status_for(r, target, results, tail)
        if ld is not None:
            f = ld["findings"].get(r["stig_id"])
            details += (f"\nAnsible Lockdown audit ({ld.get('start', '')[:10]}): "
                        + (f"{f['status']} ({f['tests']} test(s), {f['failed']} failed)" if f
                           else "no test for this finding"))
        comment = [f"How it's met: {DISPOSITIONS[r['disposition']][0]}."]
        if r["note"]:
            comment.append(r["note"])
        if r["approval"]:
            comment.append(f"Approval: {r['approval']}.")
        if r["where"]:
            comment.append("In git: " + ", ".join(r["where"]))
        if r["rules"]:
            comment.append("OpenSCAP rules: " + ", ".join(r["rules"]))
        rules.append({
            "uuid": str(uuid.uuid5(UUID_NS, f"{stig_uuid}-{r['rule_id']}")),
            "stig_uuid": stig_uuid,
            "group_id": r["vuln_id"],
            "group_title": r["group_title"],
            "rule_id": r["rule_id"],
            "rule_version": r["stig_id"],
            "rule_title": r["title"],
            "severity": r["severity"],
            "weight": r["weight"],
            "classification": "Unclassified",
            "check_content": r["check"],
            "fix_text": r["fix"],
            "discussion": r["discussion"],
            "ccis": r["ccis"],
            **({"legacy_ids": r["legacy"]} if r["legacy"] else {}),
            "status": status,
            "overrides": {},
            "comments": " ".join(comment),
            "finding_details": details,
        })
    doc = {
        "title": f"{bench['title']} - {target['label']}",
        "id": str(uuid.uuid5(UUID_NS, f"checklist-{target['name']}")),
        "cklb_version": "1.0",
        "active": False,
        "has_path": False,
        "target_data": {
            "target_type": "Computing",
            "host_name": target.get("host_name", target["name"]),
            "ip_address": target.get("ip", ""),
            "mac_address": "",
            "fqdn": "",
            "comments": target["description"],
            "role": target.get("role", "None"),
            "is_web_database": False,
            "technology_area": "UNIX OS",
            "web_db_site": "",
            "web_db_instance": "",
        },
        "stigs": [{
            "stig_name": bench["title"],
            "display_name": bench["title"].replace(" Security Technical Implementation Guide", " STIG"),
            "stig_id": bench["id"],
            "release_info": bench["release_info"].strip(),
            "version": bench["version"],
            "uuid": stig_uuid,
            "size": len(rules),
            "rules": rules,
        }],
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def generated(controls: dict) -> dict[Path, str]:
    model = build_model(controls)
    files = {TAILORING: render_tailoring(controls, model), FINDING_MAP: render_finding_map(controls, model)}
    for t in controls["targets"]:
        if load_results(t["name"]) is not None or load_lockdown(t["name"]) is not None:
            files[CHECKLISTS / f"{t['name']}.cklb"] = render_cklb(controls, model, t)
    return files


def validate(controls: dict) -> list[str]:
    errors = []
    model = build_model(controls)
    disa, ssg = model["disa"]["findings"], model["ssg"]
    for sid, entry in controls["findings"].items():
        if sid not in disa:
            errors.append(f"controls.yaml: {sid} is not a finding in the DISA benchmark")
        if entry.get("disposition") and entry["disposition"] not in DISPOSITIONS:
            errors.append(f"controls.yaml: {sid}: unknown disposition {entry['disposition']!r}")
        if entry.get("disposition") in ("exception", "not-applicable", "site-config") and not entry.get("note"):
            errors.append(f"controls.yaml: {sid}: a {entry['disposition']} needs a note explaining why")
        for rid in entry["deselect"]:
            if rid not in ssg["rules"]:
                errors.append(f"controls.yaml: {sid}: deselect {rid} is not an SSG rule with a STIG ID")
            elif sid not in ssg["rules"][rid]["stig_ids"]:
                errors.append(f"controls.yaml: {sid}: rule {rid} belongs to {ssg['rules'][rid]['stig_ids']}, not {sid}")
        for path in entry["where"]:
            if not (ROOT / path).exists():
                errors.append(f"controls.yaml: {sid}: 'where' path {path} does not exist")
        for p in entry["profiles"]:
            if p not in controls["profiles"]:
                errors.append(f"controls.yaml: {sid}: unknown profile {p}")
    for t in controls["targets"]:
        if t["profile"] not in controls["profiles"]:
            errors.append(f"controls.yaml: target {t['name']}: unknown profile {t['profile']}")
    return errors


def cmd_generate(_: argparse.Namespace) -> None:
    controls = load_controls()
    errors = validate(controls)
    if errors:
        raise SystemExit("\n".join(errors))
    for path, text in generated(controls).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


def cmd_check(_: argparse.Namespace) -> None:
    controls = load_controls()
    errors = validate(controls)
    for path, text in generated(controls).items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            errors.append(f"{path.relative_to(ROOT)} is stale: run `make stig` and commit the result")
    if errors:
        raise SystemExit("STIG check failed:\n  " + "\n  ".join(errors))
    model = build_model(controls)
    print(f"STIG check OK: {len(model['rows'])} DISA findings, every one has a disposition; generated files are current")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract-ssg")
    p.add_argument("datastream")
    p.set_defaults(func=cmd_extract_ssg)
    p = sub.add_parser("results")
    p.add_argument("arf")
    p.add_argument("--target", required=True)
    p.add_argument("--description")
    p.set_defaults(func=cmd_results)
    p = sub.add_parser("results-goss")
    p.add_argument("goss")
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_results_goss)
    sub.add_parser("generate").set_defaults(func=cmd_generate)
    sub.add_parser("check").set_defaults(func=cmd_check)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
