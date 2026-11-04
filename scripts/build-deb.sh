#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
stage_dir=$(mktemp -d)
trap 'rm -rf "$stage_dir"' EXIT HUP INT TERM
mkdir -p "$stage_dir/DEBIAN" "$stage_dir/usr/share/en-ua-switcher/en_ua" \
    "$stage_dir/usr/bin" "$stage_dir/etc/xdg/autostart" \
    "$stage_dir/usr/share/applications" "$stage_dir/usr/share/doc/en-ua-switcher" \
    "$project_dir/dist"
install -m 644 "$project_dir/packaging/control" "$stage_dir/DEBIAN/control"
install -m 644 "$project_dir"/en_ua/*.py "$stage_dir/usr/share/en-ua-switcher/en_ua/"
install -m 755 "$project_dir/bin/en-ua-switcher" "$stage_dir/usr/bin/"
install -m 644 "$project_dir/data/en-ua-switcher-autostart.desktop" "$stage_dir/etc/xdg/autostart/en-ua-switcher.desktop"
install -m 644 "$project_dir/data/en-ua-switcher.desktop" "$stage_dir/usr/share/applications/"
install -m 644 "$project_dir/README.md" "$stage_dir/usr/share/doc/en-ua-switcher/"
install -m 644 "$project_dir/LICENSE" "$stage_dir/usr/share/doc/en-ua-switcher/copyright"
find "$stage_dir" -type d -exec chmod 755 {} +
package_version=$(sed -n 's/^Version: //p' "$project_dir/packaging/control")
dpkg-deb --root-owner-group --build "$stage_dir" "$project_dir/dist/en-ua-switcher_${package_version}_all.deb"
