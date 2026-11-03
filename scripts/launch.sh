#!/bin/sh
# Takes the service live on Stellar mainnet at the HTTPS address Terraform gave the server.
#
#   npm run launch                          # the address from `terraform output` in infra/oci
#   npm run launch -- https://your.domain   # or one you give
#
# provider-kit launch opens one page where your own wallet (Freighter, xBull, Albedo, a Ledger…) approves, in one go:
# the USDC trustline on the payout account, the Stellar 8004 registration (what Stellar Agent Search finds) and a
# verification request. It saves PAY_TO and AGENT_ID in .env; `terraform apply` then sends them to the server.
# The account needs a few XLM. No key leaves your wallet.
set -eu
cd "$(dirname "$0")/.."

ORIGIN=""
case "${1:-}" in https://*) ORIGIN=$1; shift ;; esac
if [ -z "$ORIGIN" ]; then
  ORIGIN=$(terraform -chdir=infra/oci output -raw public_origin 2>/dev/null || true)
fi
case "$ORIGIN" in
  https://*) ;;
  *) echo "No HTTPS address yet: run 'terraform -chdir=infra/oci apply' first, or: npm run launch -- https://your.domain" >&2; exit 1 ;;
esac

echo "Launching at $ORIGIN (Stellar mainnet). The API runs next to the gateway in one container, so its 127.0.0.1"
echo "upstream is right: ignore the warning about it below."
node --env-file-if-exists=.env node_modules/@stellar-agent-services/provider-kit/dist/cli/index.js \
  launch --config provider.config.json --url "$ORIGIN" --no-deploy "$@"
echo
echo "Next: terraform -chdir=infra/oci apply   (sends PAY_TO, AGENT_ID and FACILITATOR_AUTH to the server and starts it)"
