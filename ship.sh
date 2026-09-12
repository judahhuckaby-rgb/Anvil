#!/bin/bash
# ship.sh — pick up freshly downloaded builds, rebuild the Anvil index, push.
#
# Put this in the anvil-repo folder and run it from anywhere:  ship
# It looks in ~/Downloads for newer copies of anything the repo already carries,
# copies them in under their proper names, regenerates the package index and
# pushes. Duplicate downloads (Relic-1.ipa, Relic 2.ipa) are handled — it always
# takes the most recently modified match.

set -e

REPO="$(cd "$(dirname "$0")" && pwd)"
DOWNLOADS="$HOME/Downloads"
cd "$REPO"

changed=""

version_of() {
    python3 - "$1" <<'PY' 2>/dev/null || echo "?"
import sys, zipfile, plistlib, re
with zipfile.ZipFile(sys.argv[1]) as z:
    name = next(n for n in z.namelist() if re.match(r"^Payload/[^/]+\.app/Info\.plist$", n))
    info = plistlib.loads(z.read(name))
print(info.get("CFBundleShortVersionString", "?"))
PY
}

# --- IPAs (TrollStore apps) -------------------------------------------------
for existing in ipas/*.ipa; do
    [ -f "$existing" ] || continue
    app="$(basename "$existing" .ipa)"
    newest="$(ls -t "$DOWNLOADS/$app"*.ipa 2>/dev/null | head -1 || true)"
    [ -n "$newest" ] || continue
    [ "$newest" -nt "$existing" ] || continue
    cp "$newest" "$existing"
    changed="$changed $app $(version_of "$existing")"
    echo "  updated $app -> $(version_of "$existing")   (from $(basename "$newest"))"
done

# --- debs (Cydia/Sileo packages) --------------------------------------------
for deb in "$DOWNLOADS"/*.deb; do
    [ -f "$deb" ] || continue
    target="debs/$(basename "$deb")"
    if [ ! -f "$target" ] || [ "$deb" -nt "$target" ]; then
        cp "$deb" "$target"
        changed="$changed $(basename "$deb")"
        echo "  added $(basename "$deb")"
    fi
done

if [ -z "$changed" ]; then
    echo "Nothing new in $DOWNLOADS — repo already up to date."
    exit 0
fi

echo
python3 update-repo.py

git add -A
if git diff --cached --quiet; then
    echo "No repo changes to commit."
    exit 0
fi
git commit -q -m "ship:$changed"
git push -q

echo
echo "Pushed:$changed"
echo "GitHub Pages takes about ten minutes to serve it."
echo "Then open the repo page on the phone and tap Install to update in place."
