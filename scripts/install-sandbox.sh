#!/usr/bin/env bash
# Install Claude Code's Bash sandbox dependencies on an Ubuntu runner.
# Ubuntu 24.04+ blocks bubblewrap's user namespaces unless AppArmor allows them.

set -euo pipefail

sudo apt-get install -y bubblewrap socat

if [ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" = "1" ]; then
  sudo tee /etc/apparmor.d/bwrap > /dev/null <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
PROFILE
  sudo systemctl reload apparmor
fi
