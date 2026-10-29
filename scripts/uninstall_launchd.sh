#!/bin/sh
# Unload and remove the LaunchAgents installed by install_launchd.sh. Data is not touched.
set -eu
cd "$(dirname "$0")/.."
exec uv run ohg launchd uninstall "$@"
