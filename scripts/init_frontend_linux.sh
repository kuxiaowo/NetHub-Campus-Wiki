#!/usr/bin/env bash

# NetHub Campus Wiki frontend-only Linux initializer.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=init_linux_common.sh
source "$SCRIPT_DIR/init_linux_common.sh"

run_initializer "frontend" "$@"
