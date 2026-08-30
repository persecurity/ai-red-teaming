#!/bin/sh
set -eu
if [ -z "${SECURITY_LEVEL:-}" ]; then
  echo "Security levels are cumulative: every higher level is more hardened and includes all controls from the levels below it."
  echo ""
  echo "  1 - No security controls"
  echo "  2 - Basic security controls"
  echo "  3 - Enhanced security controls"
  echo "  4 - Advanced security controls"
  echo "  5 - Maximum security controls"
  echo ""
  printf "Select security level [1-5]: "
  read -r SECURITY_LEVEL
fi
case "$SECURITY_LEVEL" in 1|2|3|4|5) ;; *) echo "Security level must be 1, 2, 3, 4, or 5." >&2; exit 2;; esac
export SECURITY_LEVEL
echo "Starting PG-Airlines lab at security level $SECURITY_LEVEL on http://127.0.0.1:${APP_PORT:-5001}"
docker compose up --build --wait
gateway_binding=$(docker compose port partner-gateway 8000)
echo ""
echo "PG-Airlines is ready at http://127.0.0.1:${APP_PORT:-5001}"
echo "Partner API training surface is ready at http://${gateway_binding}"
