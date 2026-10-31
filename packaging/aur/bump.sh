#!/bin/sh
# Update the PKGBUILD to a new version, taking the checksum from PyPI rather
# than trusting anyone to paste it correctly.
#
#   ./bump.sh 0.3.0
set -eu
[ $# -eq 1 ] || { echo "usage: ./bump.sh <version>" >&2; exit 2; }
VER="$1"
URL="https://files.pythonhosted.org/packages/source/v/vizdesk/vizdesk-$VER.tar.gz"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
echo "fetching $URL"
curl -fsSL -o "$TMP/sdist.tar.gz" "$URL" || { echo "vizdesk $VER is not on PyPI yet" >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then SUM=$(sha256sum "$TMP/sdist.tar.gz" | cut -d' ' -f1)
else SUM=$(shasum -a 256 "$TMP/sdist.tar.gz" | cut -d' ' -f1); fi
echo "sha256 $SUM"
sed -i.bak -e "s/^pkgver=.*/pkgver=$VER/" -e "s/^pkgrel=.*/pkgrel=1/" \
           -e "s/^sha256sums=.*/sha256sums=('$SUM')/" PKGBUILD
rm -f PKGBUILD.bak
echo "PKGBUILD updated to $VER"
echo "next, on an Arch machine:  makepkg --printsrcinfo > .SRCINFO"
