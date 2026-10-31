# Arch Linux package

`PKGBUILD` and `.SRCINFO` for publishing vizdesk to the AUR as `vizdesk`.

Every dependency is in Arch's official repositories, checked against
`archlinux.org/packages`, so this package pulls nothing else from the AUR:

| needed | repo |
|---|---|
| python | core |
| python-pandas, python-numpy, python-matplotlib | extra |
| python-openpyxl, python-pillow, python-textual | extra |
| python-build, python-installer, python-wheel, python-hatchling | extra, build only |

## Publishing it the first time

Clone the (empty) AUR repository, copy both files in, commit and send it:

```
git clone ssh://aur@aur.archlinux.org/vizdesk.git aur-vizdesk
cp PKGBUILD .SRCINFO aur-vizdesk/
cd aur-vizdesk
git add PKGBUILD .SRCINFO
git commit -m "Add vizdesk 0.2.0"
```

Then send it to the AUR with a normal push. You need an AUR account with your
SSH key added, at https://aur.archlinux.org/account/.

## Each new release

Both files must be updated, and `.SRCINFO` is generated rather than edited by
hand:

```
./bump.sh 0.3.0                        # updates pkgver and sha256 in PKGBUILD
makepkg --printsrcinfo > .SRCINFO      # regenerate, never hand-edit
makepkg -si                            # build and install locally to check
namcap PKGBUILD                        # lint: catches missing or needless deps
```

`bump.sh` runs anywhere, since it only needs curl. `makepkg` and `namcap` are
Arch tools and need an Arch machine or a container:

```
docker run --rm -it -v "$PWD":/pkg archlinux:base-devel bash
```

## Why this is not a .deb or an .rpm

A Rust program ships as one static binary, so distro packages are easy. vizdesk
is Python, so a .deb would either pin us to whatever pandas Debian ships, which
on an older Ubuntu is years behind, or bundle a private copy of numpy and
matplotlib and weigh a few hundred megabytes.

Arch is different. It tracks upstream closely and already packages every
dependency, so the PKGBUILD stays seven lines of `depends` and the package is a
few hundred kilobytes.
