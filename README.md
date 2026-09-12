# Anvil

A Cydia / Sileo / Zebra repo hosted free on GitHub Pages. Drop a `.deb` in, run one
command, push. Devices get the update the next time they refresh sources.

## One-time setup

1. Create an empty repo on GitHub named `repo` (any name works — the URL follows it).
2. From this folder:

   ```
   git init
   git add -A
   git commit -m "Anvil repo"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/repo.git
   git push -u origin main
   ```

3. On GitHub: **Settings → Pages → Source: Deploy from a branch → main / (root) → Save**.
   Give it a minute, then your repo lives at:

   ```
   https://YOUR-USERNAME.github.io/repo/
   ```

4. Run `python3 update-repo.py` once more now that the remote exists — it picks the URL
   up from git and writes the depiction and icon links into the index. Commit and push again.

## Adding the repo on a device

- **Cydia (iOS 6–11):** Sources → Edit → Add → paste the URL.
- **Sileo / Zebra:** Sources → + → paste the URL.
- Or open the repo URL in the device's browser and tap the Add button on the page.

If old Cydia refuses the HTTPS connection on a very old device, serve the same folder
over plain HTTP from the Pi (`python3 -m http.server 80` inside this folder) and add that
address instead. Same files, no changes needed.

## Shipping an update

1. Bump `Version:` in the package's `control` file and rebuild the `.deb`.
2. Drop the new `.deb` into `debs/`. Leaving the old one is fine — the newest version wins.
3. Run:

   ```
   python3 update-repo.py
   git add -A && git commit -m "Forge Classic 1.1" && git push
   ```

4. On the device: pull to refresh in Cydia/Sileo. The update shows up under Changes.

Version numbers are compared Debian-style, so `1.1` beats `1.0`, and `1.0-2` beats `1.0`.
Never reuse a version number for different content — package managers cache by version.

## Adding another package

Drop its `.deb` in `debs/` and rerun the script. Optional extras, matched by package ID:

- `depictions/<package-id>.html` — the description page shown inside Cydia/Sileo.
- `icons/<package-id>.png` — the icon in package lists (120×120 works well).

## What the script generates

`Packages`, `Packages.gz`, `Packages.bz2` (old Cydia wants the bz2), `Release`, and
`index.html`. Don't edit those by hand; they're rewritten every run. Repo name, description
and other `Release` fields live at the top of `update-repo.py`.
