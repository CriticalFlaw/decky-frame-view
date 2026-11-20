#!/usr/bin/env bash
# Build the frontend and pack an installable Decky plugin ZIP into out/.
set -euo pipefail
cd "$(dirname "$0")/.."
name="Frame View"
version=$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')
pnpm install --frozen-lockfile
pnpm run build
rm -rf out && mkdir -p "out/$name"
cp -r dist main.py plugin.json package.json LICENSE README.md "out/$name/"
mkdir -p "out/$name/py_modules"
cp -r py_modules/frameview "out/$name/py_modules/"
rm -f "out/$name/dist/"*.map
find "out/$name" -name __pycache__ -prune -exec rm -rf {} +
(cd out && zip -qr "decky-frame-view-$version.zip" "$name")
echo "out/decky-frame-view-$version.zip"
