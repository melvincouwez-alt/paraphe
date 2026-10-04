#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 melvincouwez-alt
#
# Build dist/paraphe_<version>_<arch>.deb. PyMuPDF and pyHanko are not
# packaged for Ubuntu at the versions Paraphe needs, so they are installed
# with pip into /usr/lib/paraphe/vendor.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
version=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$root/paraphe/__init__.py")
arch=$(dpkg --print-architecture)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
app_id=io.github.melvincouwez.Paraphe

lib="$stage/usr/lib/paraphe"
mkdir -p "$lib"
cp -r "$root/paraphe" "$lib/"
find "$lib" -name __pycache__ -prune -exec rm -rf {} +
python3 -m pip --version >/dev/null 2>&1 && pip="python3 -m pip" || pip="$root/.venv/bin/pip"
$pip install --quiet --no-compile --target "$lib/vendor" pymupdf "pyhanko[opentype]"
rm -rf "$lib"/vendor/bin

install -Dm755 /dev/stdin "$stage/usr/bin/paraphe" <<'LAUNCHER'
#!/bin/sh
PYTHONPATH=/usr/lib/paraphe:/usr/lib/paraphe/vendor exec python3 -m paraphe "$@"
LAUNCHER
install -Dm644 "$root/data/$app_id.desktop" "$stage/usr/share/applications/$app_id.desktop"
install -Dm644 "$root/data/$app_id.metainfo.xml" "$stage/usr/share/metainfo/$app_id.metainfo.xml"
install -Dm644 "$root/data/$app_id.svg" "$stage/usr/share/icons/hicolor/scalable/apps/$app_id.svg"
for size in 16 24 32 48 64 128; do
    install -Dm644 "$root/data/icons/app/$size.svg" "$stage/usr/share/icons/hicolor/${size}x${size}/apps/$app_id.svg"
done
for icon in "$root"/data/icons/hicolor/scalable/actions/*.svg; do
    install -Dm644 "$icon" "$stage/usr/share/paraphe/icons/hicolor/scalable/actions/$(basename "$icon")"
done
install -Dm644 "$root/LICENSE" "$stage/usr/share/doc/paraphe/copyright"

mkdir -p "$stage/DEBIAN"
size=$(du -sk "$stage/usr" | cut -f1)
cat > "$stage/DEBIAN/control" <<CONTROL
Package: paraphe
Version: $version
Architecture: $arch
Maintainer: melvincouwez-alt <301110918+melvincouwez-alt@users.noreply.github.com>
Installed-Size: $size
Depends: python3 (>= 3.12), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-granite-7.0
Section: graphics
Priority: optional
Homepage: https://github.com/melvincouwez-alt/paraphe
Description: PDF editor for elementary OS
 Annotate PDF files (highlight, underline, strike out, text, notes,
 drawing), fill in forms, sign by hand or with a certificate, reorder,
 rotate, extract, merge and split pages.
CONTROL
cat > "$stage/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
POSTINST
chmod 755 "$stage/DEBIAN/postinst"

mkdir -p "$root/dist"
out="$root/dist/paraphe_${version}_${arch}.deb"
dpkg-deb --root-owner-group -Zxz --build "$stage" "$out" >/dev/null
echo "$out"
