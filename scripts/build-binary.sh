#!/usr/bin/env bash
# Build the standalone `zadctl` for this machine, exactly as the release does.
#
# The flags live here rather than only in .github/workflows/release-binaries.yml so that a
# local build and a released one are the same thing. They drifted apart once already: a
# local build without --no-deployment-flag=self-execution silently accepted `-c` while the
# published one died on it, and one without a commit in the cache path overwrote the cache
# of an installed binary and left it being killed on start with no message.
#
#   scripts/build-binary.sh                 # build into dist/
#   scripts/build-binary.sh --install       # and copy it into ~/.local/bin
#
# Takes a few minutes: Nuitka compiles, it does not bundle.
set -euo pipefail

cd "$(dirname "$0")/.."

INSTALL=0
[ "${1:-}" = "--install" ] && INSTALL=1

VERSION=$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2)
NUMERIC="${VERSION%%-*}"          # Nuitka's version fields take digits and dots only
SHA=$(git rev-parse --short=12 HEAD)
DIRTY=""
git diff --quiet || DIRTY=" (with uncommitted changes)"

echo "Building zadctl $VERSION from $SHA$DIRTY"

# The cache key is the commit, not the version: two builds of the same version would
# otherwise share an unpacked runtime, and the second one is killed on start.
uv run --with nuitka python -m nuitka \
  --standalone --onefile --onefile-cache-mode=cached \
  --onefile-tempdir-spec="{CACHE_DIR}/RijksICTGilde/zadctl/${SHA}" \
  --no-deployment-flag=self-execution \
  --company-name=RijksICTGilde --product-name=zadctl \
  --file-version="$NUMERIC" --product-version="$NUMERIC" \
  --output-filename=zadctl --output-dir=dist \
  --include-package=zad_cli \
  --include-data-files=api/upstream-openapi.json=zad_cli/api/upstream-openapi.json \
  --include-data-files=src/zad_cli/data/services-snapshot.json=zad_cli/data/services-snapshot.json \
  --assume-yes-for-downloads \
  src/zad_cli/__main__.py

# The same smoke test the release runs, for the same reason: the vendored spec and the
# service catalogue are read from paths next to the modules, which a bundler can leave
# behind without saying so.
echo "Checking the build runs and brought its data along"
./dist/zadctl --version
./dist/zadctl --help > /dev/null
ZAD_CATALOG_OFFLINE=1 ./dist/zadctl service list > /dev/null
ZAD_PROJECT_ID=p ZAD_API_KEY=k ZAD_CATALOG_OFFLINE=1 \
  ./dist/zadctl env add -c web FOO=bar --dry-run > /dev/null

if [ "$INSTALL" = "1" ]; then
  mkdir -p "$HOME/.local/bin"
  # Copy beside it and rename over it: `cp` onto a binary that is running truncates the
  # file another shell is executing, and a rename is atomic, so a command already in
  # flight keeps the old inode and finishes normally.
  cp dist/zadctl "$HOME/.local/bin/.zadctl.new"
  mv -f "$HOME/.local/bin/.zadctl.new" "$HOME/.local/bin/zadctl"
  echo "Installed in ~/.local/bin/zadctl"
  command -v zadctl > /dev/null || echo "Note: ~/.local/bin is not on your PATH."
else
  echo "Built: dist/zadctl  (--install copies it into ~/.local/bin)"
fi
