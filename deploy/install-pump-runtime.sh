#!/usr/bin/env bash
# Root-owned runtime outside ProtectHome; no global Node or service hardening changes.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Runtime installation requires root.' >&2; exit 1; }
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$REPO_DIR/pump_adapter/.node-version")"
[ "$VERSION" = 22.23.2 ] || { echo 'Runtime pin/checksum mismatch.' >&2; exit 1; }
case "$(uname -m)" in
  x86_64) ARCH=x64; SHA=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307 ;;
  aarch64) ARCH=arm64; SHA=fff4078c5def658577f92c88db7db3bc0072924bfb93fe52c1e744a54e94abb8 ;;
  *) echo 'Unsupported Pump runtime architecture.' >&2; exit 1 ;;
esac
DEST="/opt/orcagent-runtime/node-v$VERSION"
if [ ! -x "$DEST/bin/node" ]; then
  mkdir -p /opt/orcagent-runtime
  chmod 755 /opt/orcagent-runtime
  TMP="$(mktemp -d /opt/orcagent-runtime/.install-XXXXXX)"
  trap 'rm -rf "$TMP"' EXIT
  ARCHIVE="node-v$VERSION-linux-$ARCH.tar.xz"
  curl --proto '=https' --tlsv1.2 -fsS --retry 3 --max-time 180 \
    "https://nodejs.org/dist/v$VERSION/$ARCHIVE" -o "$TMP/$ARCHIVE"
  echo "$SHA  $TMP/$ARCHIVE" | sha256sum -c -
  tar -xJf "$TMP/$ARCHIVE" -C "$TMP" --no-same-owner
  chown -R root:root "$TMP/node-v$VERSION-linux-$ARCH"
  chmod -R go-w "$TMP/node-v$VERSION-linux-$ARCH"
  mv "$TMP/node-v$VERSION-linux-$ARCH" "$DEST"
fi
[ "$(stat -c '%U' "$DEST/bin/node")" = root ] || { echo 'Pump runtime must be root-owned.' >&2; exit 1; }
ORCAGENT_PUMP_NODE="$DEST/bin/node" bash "$REPO_DIR/pump_adapter/run-node.sh" --version
