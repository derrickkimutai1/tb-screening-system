#!/usr/bin/env bash
#
# Wire GitHub Actions up to deploy this application, once.
#
# After this runs, every push to main that passes its tests builds an image and
# points the running application at it. Nothing manual afterwards.
#
# It needs two sign-ins done first, both in a browser, because they are the
# operator's own credentials and belong to nobody else:
#
#     az login
#     gh auth login
#
# Then:
#
#     bash deploy/wire-up-github-deploy.sh
#
# What it does, in order: finds the container app and the resource group it is
# in, creates a service principal scoped to that group and no wider, hands the
# credential to GitHub as a secret, sets the three variables the workflow
# reads, and starts a run. The credential is piped from one command to the
# other and is never printed, written to a file, or placed in a shell variable
# that survives the line it is used on.
#
# Safe to run twice: the service principal is recreated and the secret
# replaced, which also makes it the way to rotate the credential.

set -euo pipefail

APP="${AZURE_APP_NAME:-tb-screening}"
SP_NAME="${SP_NAME:-tb-screening-deploy}"

say() { printf '\n== %s\n' "$1"; }
die() { printf '\n!! %s\n' "$1" >&2; exit 1; }

command -v az >/dev/null || die "az not found. Install the Azure CLI first."
command -v gh >/dev/null || die "gh not found. Install the GitHub CLI first."

az account show >/dev/null 2>&1 || die "Not signed in to Azure. Run: az login"
gh auth status >/dev/null 2>&1 || die "Not signed in to GitHub. Run: gh auth login"

say "Finding the application"
# Asked for by name across the whole subscription rather than assumed to sit in
# a group of the same name, because it need not.
read -r GROUP FQDN <<<"$(az containerapp list \
    --query "[?name=='${APP}'].[resourceGroup, properties.configuration.ingress.fqdn]" \
    -o tsv | head -1)"
[ -n "${GROUP:-}" ] || die "No container app called '${APP}' in this subscription."
printf '   %s is in resource group %s\n' "$APP" "$GROUP"
printf '   reachable at https://%s/\n' "$FQDN"

SUBSCRIPTION="$(az account show --query id -o tsv)"
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
printf '   repository %s\n' "$REPO"

say "Creating a credential scoped to that resource group"
# --sdk-auth prints the JSON block the azure/login action expects. It is a
# password: piped straight into gh, never echoed and never stored on disk.
# The pipeline's exit status is checked because gh succeeding on empty input
# would leave an empty secret and a deploy that fails much later.
set -o pipefail
if ! az ad sp create-for-rbac \
        --name "$SP_NAME" \
        --role contributor \
        --scopes "/subscriptions/${SUBSCRIPTION}/resourceGroups/${GROUP}" \
        --sdk-auth 2>/dev/null \
    | gh secret set AZURE_CREDENTIALS --repo "$REPO"; then
    die "Could not create the credential. If the tenant refuses to create
    service principals, this repository cannot deploy itself; deploy by hand
    instead - docs/deployment-azure.md, 'Deploying by hand'."
fi
printf '   AZURE_CREDENTIALS set\n'

say "Setting the variables the workflow reads"
gh variable set AZURE_DEPLOY --repo "$REPO" --body "true"
gh variable set AZURE_APP_NAME --repo "$REPO" --body "$APP"
gh variable set AZURE_RESOURCE_GROUP --repo "$REPO" --body "$GROUP"
gh variable set AZURE_HEALTH_URL --repo "$REPO" --body "https://${FQDN}/health/"
gh variable list --repo "$REPO"

say "Starting a run"
gh workflow run publish-image.yml --repo "$REPO" --ref main
printf '   watch it with: gh run watch --repo %s\n' "$REPO"

say "Done"
cat <<EOF
   Every push to main that passes its tests will now deploy itself, and the
   run fails rather than going green if the application does not answer
   /health/ afterwards.

   To check the live release at any time:
     curl -s https://${FQDN}/health/
EOF
