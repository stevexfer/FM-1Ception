#!/usr/bin/env python3
"""A page of the firmwares whose source holds outside code: each one's name and description (as the Cloud's lists
give them), its repository, and its CODE FROM (as FM-1Ception shows it: outside projects, not other FM-1 firmwares).

  fwinfo.py --out FILE [--facts Resources/FirmwareFacts.json] [--support DIR]

DIR is FM-1Ception's support folder, for the lists (CloudCatalog*.json). The page is one self-contained file.
"""
import argparse
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUPPORT = Path.home() / "Library/Application Support/Xfer Records/FM-1Ception"


def key_of(repo):
    s = re.sub(r"^https?://", "", (repo or "").strip())
    s = re.sub(r"^(www\.)?github\.com/", "", s)
    parts = [p for p in s.split("?")[0].split("/") if p]
    if len(parts) < 2 or "." in parts[0]:
        return ""
    return (parts[0] + "/" + re.sub(r"\.git$", "", parts[1])).lower()


def listed(support):
    """repository -> (name, description), the lists' first that says each"""
    out = {}

    def add(repo, name, about):
        k = key_of(repo)
        if not k:
            return
        n, a = out.get(k, ("", ""))
        out[k] = (n or name or "", a or about or "")

    mutant = json.loads((support / "CloudCatalog.json").read_text())
    for e in mutant.get("entries", []):
        if e.get("kind", "firmware") == "firmware":
            add(e.get("repo"), e.get("name"), e.get("description"))
    for e in json.loads((support / "CloudCatalog-2.json").read_text()).get("firmwares", []):
        add(e.get("repo"), e.get("name"), e.get("about"))
    for e in json.loads((support / "CloudCatalog-hub.json").read_text()).get("firmwares", []):
        add(e.get("repo") or e.get("source"), e.get("name"), e.get("what"))
    return out


def code_from(f):
    names = []
    for o in f.get("origins") or []:
        if o.get("how") in ("code", "port") and not o.get("fm1"):
            n = o["project"].split(" (")[0].strip() or o["project"]
            if n not in names:
                names.append(n)
    return names


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Outside code in FM-1 firmwares</title>
<style>
:root {{ --room: #18191b; --header: #111214; --tray: #2b2c2f; --silk: #c9c6bd; --dim: #8c8a85; --amber: #f2a33a; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--room); color: var(--silk); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif; }}
header {{ padding: 28px 32px 16px; }}
h1 {{ margin: 0 0 6px; font-size: 22px; font-weight: 650; letter-spacing: 0.01em; }}
.caption {{ margin: 0; color: var(--dim); font-size: 13px; max-width: 900px; }}
.tools {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 0 32px 16px; }}
input[type=search] {{ width: 300px; height: 30px; padding: 0 10px; border: 1px solid var(--tray); border-radius: 6px; background: var(--header); color: var(--silk); font: inherit; }}
input[type=search]:focus {{ outline: none; border-color: var(--amber); }}
.pill {{ height: 26px; padding: 0 10px; border: 1px solid var(--tray); border-radius: 13px; background: none; color: var(--silk); font-family: inherit; font-size: 12px; line-height: 24px; cursor: pointer; }}
.pill b {{ color: var(--dim); font-weight: 500; margin-left: 4px; }}
.pill.on {{ border-color: var(--amber); color: var(--amber); }}
.count {{ color: var(--dim); font-size: 12px; margin-left: 4px; }}
.wrap {{ padding: 0 32px 40px; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
col.name {{ width: 15%; }} col.desc {{ width: 43%; }} col.code {{ width: 24%; }} col.url {{ width: 18%; }}
th {{ position: sticky; top: 0; background: var(--header); color: var(--dim); font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; text-align: left; padding: 9px 12px; border-bottom: 1px solid #000; }}
td {{ padding: 9px 12px; vertical-align: top; border-bottom: 1px solid var(--tray); }}
tr:nth-child(even) td {{ background: #1c1d20; }}
td.name {{ font-weight: 600; overflow-wrap: anywhere; }}
td.desc {{ color: var(--dim); font-size: 13px; }}
td.code {{ font-size: 13px; }}
td.url {{ font-size: 13px; overflow-wrap: anywhere; }}
a {{ color: var(--silk); text-decoration: none; border-bottom: 1px solid var(--tray); }}
a:hover {{ color: var(--amber); border-color: var(--amber); }}
footer {{ padding: 0 32px 32px; color: var(--dim); font-size: 12px; }}
</style>
</head>
<body>
<header>
<h1>Outside code in FM-1 firmwares</h1>
<p class="caption">{n} firmwares for the M-VAVE FM-1 whose source holds or ports code from outside projects
(other FM-1 firmwares and platforms left out). From FM-1Ception's firmware facts: each repository read at its commit of {scanned}.</p>
</header>
<div class="tools">
<input type="search" id="q" placeholder="Search names, descriptions, code from" autocomplete="off">
{pills}
<span class="count" id="count">{n} shown</span>
</div>
<div class="wrap">
<table>
<colgroup><col class="name"><col class="desc"><col class="code"><col class="url"></colgroup>
<thead><tr><th>Name</th><th>Description</th><th>Code from</th><th>URL</th></tr></thead>
<tbody id="rows">
{rows}
</tbody>
</table>
</div>
<footer>FM-1Ception by Xfer Records</footer>
<script>
const q = document.getElementById("q"), count = document.getElementById("count");
const rows = [...document.querySelectorAll("#rows tr")], pills = [...document.querySelectorAll(".pill")];
const total = rows.length;
function filter() {{
  const words = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
  let shown = 0;
  for (const r of rows) {{
    const hay = r.textContent.toLowerCase();
    const on = words.every((w) => hay.includes(w));
    r.style.display = on ? "" : "none";
    if (on) shown++;
  }}
  for (const p of pills) p.classList.toggle("on", q.value === p.dataset.q);
  count.textContent = shown === total ? total + " shown" : shown + " of " + total + " shown";
}}
q.addEventListener("input", filter);
for (const p of pills) p.addEventListener("click", () => {{ q.value = q.value === p.dataset.q ? "" : p.dataset.q; filter(); }});
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--facts", default=str(HERE.parent / "Resources" / "FirmwareFacts.json"))
    ap.add_argument("--support", default=str(SUPPORT))
    a = ap.parse_args()
    db = json.loads(Path(a.facts).read_text())
    names = listed(Path(a.support))
    rows = []
    for k, f in db["firmwares"].items():
        code = code_from(f)
        if not code:
            continue
        name, about = names.get(k, ("", ""))
        rows.append((name or f["repo"].split("/")[-1], (about or f.get("summary") or "").strip(), code, "https://github.com/" + f["repo"]))
    rows.sort(key=lambda r: r[0].lower())

    counts = {}
    for r in rows:
        for p in r[2]:
            counts[p] = counts.get(p, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:10]
    e = html.escape
    pills = "\n".join(f'<button class="pill" data-q="{e(p)}">{e(p)}<b>{n}</b></button>' for p, n in top)
    body = "\n".join(
        f'<tr><td class="name">{e(n)}</td><td class="desc">{e(d)}</td><td class="code">{e(", ".join(c))}</td>'
        f'<td class="url"><a href="{e(u)}" target="_blank" rel="noopener">{e(u.removeprefix("https://"))}</a></td></tr>'
        for n, d, c, u in rows)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(PAGE.format(n=len(rows), scanned=db.get("scanned", ""), pills=pills, rows=body))
    print(f"{len(rows)} firmwares -> {out}")


if __name__ == "__main__":
    main()
