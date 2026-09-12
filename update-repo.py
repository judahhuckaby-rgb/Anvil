#!/usr/bin/env python3
"""
Rebuilds the package index for this repo.

Run it from the repo folder after adding or replacing a .deb in debs/:

    python3 update-repo.py
    git add -A && git commit -m "Forge Classic 1.1" && git push

It reads every .deb in debs/, writes Packages / Packages.gz / Packages.bz2,
refreshes Release, and regenerates index.html. Any .ipa in ipas/ is listed on
the page too, with a one-tap TrollStore install link. Pure standard library, so it
works on a stock Mac with no extra tools installed.
"""

import bz2
import gzip
import hashlib
import html
import io
import os
import re
import plistlib
import subprocess
import sys
import tarfile
import urllib.parse
import zipfile

# ---------------------------------------------------------------- repo details

REPO = {
    "Origin": "Anvil",
    "Label": "Anvil",
    "Suite": "stable",
    "Version": "1.0",
    "Codename": "anvil",
    "Architectures": "iphoneos-arm iphoneos-arm64",
    "Components": "main",
    "Description": "Tweaks and apps by Judah",
}

HERE = os.path.dirname(os.path.abspath(__file__))
DEBS = os.path.join(HERE, "debs")

# ---------------------------------------------------------------- .deb parsing


def read_ar_members(path):
    """Yields (name, bytes) for each member of an ar archive (a .deb is one)."""
    with open(path, "rb") as handle:
        if handle.read(8) != b"!<arch>\n":
            raise ValueError("%s is not a .deb" % path)
        while True:
            header = handle.read(60)
            if len(header) < 60:
                return
            name = header[0:16].decode("ascii", "replace").strip()
            size = int(header[48:58].decode("ascii", "replace").strip())
            data = handle.read(size)
            if size % 2:
                handle.read(1)
            yield name.rstrip("/"), data


def control_fields(deb_path):
    """Returns the control file of a .deb as an ordered dict of field -> value."""
    control_bytes = None
    for name, data in read_ar_members(deb_path):
        if not name.startswith("control.tar"):
            continue
        fileobj = io.BytesIO(data)
        mode = "r:gz" if name.endswith(".gz") else ("r:xz" if name.endswith(".xz") else "r:*")
        with tarfile.open(fileobj=fileobj, mode=mode) as tar:
            for member in tar.getmembers():
                if os.path.basename(member.name) == "control":
                    control_bytes = tar.extractfile(member).read()
                    break
    if control_bytes is None:
        raise ValueError("no control file inside %s" % deb_path)

    fields, key = {}, None
    for line in control_bytes.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and key:
            fields[key] += "\n" + line.strip()
        else:
            key, _, value = line.partition(":")
            key = key.strip()
            fields[key] = value.strip()
    return fields


def hashes(path):
    md5, sha1, sha256 = hashlib.md5(), hashlib.sha1(), hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()


def version_key(value):
    """Rough Debian version ordering — good enough to pick the newest build."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


# ---------------------------------------------------------------- .ipa parsing


def ipa_info(path):
    """Pulls name / version / minimum iOS out of an .ipa's Info.plist."""
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if re.match(r"^Payload/[^/]+\.app/Info\.plist$", n)]
        if not names:
            raise ValueError("no app bundle inside %s" % path)
        info = plistlib.loads(archive.read(names[0]))
    return {
        "name": info.get("CFBundleName") or info.get("CFBundleDisplayName") or os.path.basename(path),
        "version": info.get("CFBundleShortVersionString", "") or str(info.get("CFBundleVersion", "")),
        "minimum": info.get("MinimumOSVersion", ""),
        "identifier": info.get("CFBundleIdentifier", ""),
        "file": os.path.basename(path),
        "size": os.path.getsize(path),
    }


def collect_ipas():
    folder = os.path.join(HERE, "ipas")
    if not os.path.isdir(folder):
        return []
    apps = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".ipa"):
            continue
        try:
            apps.append(ipa_info(os.path.join(folder, name)))
            print("  listed %s" % name)
        except Exception as error:
            print("  skipping %s (%s)" % (name, error))
    return apps


# ---------------------------------------------------------------- base url


def base_url():
    """Guesses the public URL from the git remote, e.g. https://user.github.io/repo/"""
    override = os.environ.get("REPO_URL")
    if override:
        return override.rstrip("/") + "/"
    try:
        remote = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=HERE,
                                         stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""
    match = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", remote)
    if not match:
        return ""
    user, repo = match.group(1), match.group(2)
    return "https://%s.github.io/%s/" % (user.lower(), repo)


# ---------------------------------------------------------------- index build


def build():
    if not os.path.isdir(DEBS):
        sys.exit("No debs/ folder here. Put your .deb files in debs/ and run this again.")

    url = base_url()
    newest = {}
    for name in sorted(os.listdir(DEBS)):
        if not name.endswith(".deb"):
            continue
        path = os.path.join(DEBS, name)
        fields = control_fields(path)
        package = fields.get("Package")
        if not package:
            print("  skipping %s (no Package field)" % name)
            continue
        previous = newest.get(package)
        if previous and version_key(previous[0].get("Version", "0")) >= version_key(fields.get("Version", "0")):
            continue
        newest[package] = (fields, path, name)

    stanzas = []
    for package in sorted(newest):
        fields, path, name = newest[package]
        md5, sha1, sha256 = hashes(path)
        fields["Filename"] = "debs/" + name
        fields["Size"] = str(os.path.getsize(path))
        fields["MD5sum"] = md5
        fields["SHA1"] = sha1
        fields["SHA256"] = sha256
        depiction = os.path.join(HERE, "depictions", package + ".html")
        if url and os.path.exists(depiction):
            fields["Depiction"] = "%sdepictions/%s.html" % (url, package)
        icon = os.path.join(HERE, "icons", package + ".png")
        if url and os.path.exists(icon):
            fields["Icon"] = "%sicons/%s.png" % (url, package)
        order = ["Package", "Name", "Version", "Architecture", "Description", "Author", "Maintainer",
                 "Section", "Depends", "Conflicts", "Replaces", "Depiction", "Icon", "Filename",
                 "Size", "MD5sum", "SHA1", "SHA256"]
        lines = []
        for key in order:
            if key in fields and fields[key]:
                lines.append("%s: %s" % (key, fields[key]))
        for key in fields:
            if key not in order and fields[key]:
                lines.append("%s: %s" % (key, fields[key]))
        stanzas.append("\n".join(lines))
        print("  indexed %s %s" % (package, fields.get("Version", "")))

    packages = ("\n\n".join(stanzas) + "\n").encode("utf-8")
    write(os.path.join(HERE, "Packages"), packages)
    write(os.path.join(HERE, "Packages.gz"), gzip.compress(packages, 9))
    write(os.path.join(HERE, "Packages.bz2"), bz2.compress(packages, 9))

    release = "\n".join("%s: %s" % (key, value) for key, value in REPO.items()) + "\n"
    write(os.path.join(HERE, "Release"), release.encode("utf-8"))

    apps = collect_ipas()

    write(os.path.join(HERE, ".nojekyll"), b"")
    write(os.path.join(HERE, "index.html"), landing_page(newest, apps, url).encode("utf-8"))

    print("\nWrote Packages, Packages.gz, Packages.bz2, Release and index.html")
    if url:
        print("Repo URL: %s" % url)
    else:
        print("Tip: once this folder is a git repo with a GitHub remote, the URL fills itself in.")
    print("Next: git add -A && git commit -m \"update\" && git push")


def write(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def human_size(size):
    mb = size / (1024.0 * 1024.0)
    return "%.1f MB" % mb if mb >= 1 else "%.0f KB" % (size / 1024.0)


def landing_page(newest, apps, url):
    rows = []
    for package in sorted(newest):
        fields = newest[package][0]
        rows.append(
            "<tr><td><strong>{name}</strong><br><span class=id>{pkg}</span></td>"
            "<td>{version}</td><td>{desc}</td></tr>".format(
                name=html.escape(fields.get("Name", package)),
                pkg=html.escape(package),
                version=html.escape(fields.get("Version", "")),
                desc=html.escape(fields.get("Description", "").split("\n")[0]),
            )
        )
    app_rows = []
    for app in apps:
        ipa_url = "%sipas/%s" % (url, app["file"]) if url else app["file"]
        install = "apple-magnifier://install?url=" + urllib.parse.quote(ipa_url, safe="")
        meta = ["v" + app["version"]] if app["version"] else []
        if app["minimum"]:
            meta.append("iOS %s+" % app["minimum"])
        meta.append(human_size(app["size"]))
        app_rows.append(
            "<tr><td><strong>{name}</strong><br><span class=id>{meta}</span></td>"
            "<td class=right><a class=\"button small\" href=\"{install}\">Install</a>"
            "<a class=\"plain\" href=\"{ipa}\">.ipa</a></td></tr>".format(
                name=html.escape(app["name"]),
                meta=html.escape(" · ".join(meta)),
                install=html.escape(install),
                ipa=html.escape(ipa_url),
            )
        )
    apps_section = APPS_SECTION.format(rows="\n".join(app_rows)) if app_rows else ""
    plain = url.replace("https://", "").replace("http://", "") if url else "your-repo-url/"
    return PAGE.format(origin=html.escape(REPO["Origin"]),
                       description=html.escape(REPO["Description"]),
                       url=html.escape(url or "your-repo-url/"),
                       plain=html.escape(plain),
                       rows="\n".join(rows),
                       apps=apps_section)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{origin}</title>
<style>
  body {{ font: 16px/1.5 -apple-system, system-ui, "Helvetica Neue", Arial, sans-serif;
         margin: 0; padding: 32px 20px 60px; color: #1c1c1e; background: #f6f6f8; }}
  .wrap {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 30px; margin: 0 0 4px; }}
  p.sub {{ color: #6b6b76; margin: 0 0 24px; }}
  .card {{ background: #fff; border-radius: 14px; padding: 18px 20px; margin-bottom: 18px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  code {{ background: #ececf1; padding: 2px 6px; border-radius: 5px; font-size: 14px; word-break: break-all; }}
  a.button {{ display: inline-block; background: #ff7a1a; color: #fff; text-decoration: none;
             padding: 11px 18px; border-radius: 10px; font-weight: 600; margin: 6px 8px 6px 0; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: 10px 6px; border-top: 1px solid #ececf1; vertical-align: top; font-size: 15px; }}
  tr:first-child td {{ border-top: none; }}
  .id {{ color: #8a8a95; font-size: 12px; }}
  td.right {{ text-align: right; white-space: nowrap; }}
  a.button.small {{ padding: 7px 14px; margin: 0 0 0 6px; font-size: 14px; }}
  a.plain {{ color: #6b6b76; text-decoration: none; font-size: 13px; margin-left: 10px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{origin}</h1>
  <p class="sub">{description}</p>

  <div class="card">
    <strong>Add this repo</strong>
    <p><code>{url}</code></p>
    <a class="button" href="cydia://url/https://cydia.saurik.com/api/share#?source={url}">Add to Cydia</a>
    <a class="button" href="sileo://source/{url}">Add to Sileo</a>
    <a class="button" href="zbra://sources/add/{url}">Add to Zebra</a>
    <p style="color:#6b6b76;font-size:14px;margin-bottom:0">On an older device, open Cydia → Sources → Edit → Add and type <code>{plain}</code></p>
  </div>

  <div class="card">
    <strong>Packages</strong>
    <p style="color:#6b6b76;font-size:14px;margin:2px 0 10px">Install these through Cydia, Sileo or Zebra after adding the repo above.</p>
    <table>
{rows}
    </table>
  </div>
{apps}
</div>
</body>
</html>
"""

APPS_SECTION = """
  <div class="card">
    <strong>Apps for TrollStore</strong>
    <p style="color:#6b6b76;font-size:14px;margin:2px 0 10px">Open this page on the device and tap Install. Needs TrollStore, with its URL scheme enabled.</p>
    <table>
{rows}
    </table>
  </div>
"""

if __name__ == "__main__":
    build()
