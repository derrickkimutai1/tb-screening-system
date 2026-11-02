#!/usr/bin/env bash
# Create the Azure hosting for this application, once.
#
# Run it in Azure Cloud Shell (the >_ button in the Azure portal). Cloud Shell
# already has the Azure CLI and is already signed in as you, so nothing needs
# installing on the laptop and no credential is typed into a local file.
#
#   bash azure-setup.sh
#
# What it makes:
#
#   a resource group          everything below lives in it, so deleting the
#                             group removes the whole deployment in one step
#   a Container Apps
#   environment               the shared network and logging the app runs in
#   a container app           the application itself, pulling the image that
#                             GitHub Actions published
#
# Why Container Apps rather than a virtual machine: the free grant is
# 180,000 vCPU-seconds and 360,000 GiB-seconds per subscription per month, and
# an app scaled to zero is not billed at all. At the size set below that is
# about fifty hours of real traffic a month before the student credit is
# touched, which is far more than a marked demonstration uses.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-tb-screening}"
LOCATION="${LOCATION:-westeurope}"
ENVIRONMENT="${ENVIRONMENT:-tb-screening-env}"
APP_NAME="${APP_NAME:-tb-screening}"

# One vCPU and two gibibytes. The model is held in memory for the life of the
# process and is most of the footprint; half a gibibyte, which is what several
# free tiers offer, cannot load TensorFlow at all.
CPU="${CPU:-1.0}"
MEMORY="${MEMORY:-2.0Gi}"

# The port the container listens on, from the Dockerfile.
PORT="${PORT:-7860}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
# Each answer can arrive in the environment instead of being typed:
#
#     export IMAGE=... DATABASE_URL=... SECRET_KEY=...
#     bash azure-setup.sh
#
# which is the reliable way to hand it a connection string. A web terminal
# does not always accept a paste, and read -s shows nothing while a value is
# being entered, so a paste that never arrived looked exactly like one that
# worked: the questions marched past and the run ended with empty answers.
#
# A variable that is already set is used rather than asked for, even when it
# is deliberately empty, because deploying without Google sign-in is a valid
# choice rather than a question worth insisting on.
provided() { [ -n "${!1+set}" ]; }

ask() {
    local prompt="$1" var="$2" value
    if provided "$var"; then printf '  %s: (from the environment)\n' "$prompt"; return; fi
    read -r -p "  ${prompt}: " value
    printf -v "$var" '%s' "$value"
}

ask_hidden() {
    local prompt="$1" var="$2" value
    if provided "$var"; then printf '  %s: (from the environment)\n' "$prompt"; return; fi
    read -r -s -p "  ${prompt}: " value
    echo
    printf -v "$var" '%s' "$value"
}

say "Azure hosting for the TB screening system"
echo "  Nothing is created until every question below is answered."
echo

ask       "Image published by GitHub (ghcr.io/owner/repo:tag)" IMAGE
ask_hidden "Neon connection string (postgresql://...)"         DATABASE_URL
ask_hidden "Django secret key"                                 SECRET_KEY
ask       "Google OAuth client id"                             GOOGLE_ID
ask_hidden "Google OAuth client secret"                        GOOGLE_SECRET
ask       "Sending email address"                              EMAIL_USER
ask_hidden "Email app password (no spaces)"                    EMAIL_PASSWORD

for required in IMAGE DATABASE_URL SECRET_KEY; do
    if [ -z "${!required}" ]; then
        echo "  ${required} cannot be empty. Nothing was created." >&2
        exit 1
    fi
done

say "Making sure the subscription can run container apps"
# A subscription that has never used these services has to register them
# first, which is a one-off and can take a few minutes.
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az extension add --name containerapp --upgrade --only-show-errors

say "Creating the resource group ${RESOURCE_GROUP} in ${LOCATION}"
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none

say "Creating the environment ${ENVIRONMENT}"
az containerapp env create \
    --name "$ENVIRONMENT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none

# Django refuses a request whose Host header it does not recognise, and rejects
# a form post from an origin it does not trust, so three settings have to carry
# the name the app will answer at. That name is the app name joined to the
# environment's default domain, which the environment knows as soon as it
# exists, so asking it here makes those settings part of the creation.
#
# Setting them in a second update afterwards is what the first deployment did,
# and it cost an hour. The container had already started by then, so it was
# running with no allowed host and answered HTTP 400 to everything, including
# the health check at the end of this script. An express environment rejects
# --revision-suffix and a revision restart errored, so there was no clean way
# to make it read the new values: it took a scale to zero and a wake.
DOMAIN="$(az containerapp env show \
    --name "$ENVIRONMENT" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.defaultDomain \
    --output tsv)"
HOST="${APP_NAME}.${DOMAIN}"

say "Creating the application ${APP_NAME} at ${HOST}"
az containerapp create \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --environment "$ENVIRONMENT" \
    --image "$IMAGE" \
    --target-port "$PORT" \
    --ingress external \
    --cpu "$CPU" \
    --memory "$MEMORY" \
    --min-replicas 0 \
    --max-replicas 1 \
    --secrets \
        "django-secret-key=${SECRET_KEY}" \
        "database-url=${DATABASE_URL}" \
        "google-client-id=${GOOGLE_ID}" \
        "google-client-secret=${GOOGLE_SECRET}" \
        "email-password=${EMAIL_PASSWORD}" \
    --env-vars \
        "DJANGO_SECRET_KEY=secretref:django-secret-key" \
        "DATABASE_URL=secretref:database-url" \
        "GOOGLE_OAUTH_CLIENT_ID=secretref:google-client-id" \
        "GOOGLE_OAUTH_CLIENT_SECRET=secretref:google-client-secret" \
        "EMAIL_HOST_PASSWORD=secretref:email-password" \
        "EMAIL_HOST=smtp.gmail.com" \
        "EMAIL_PORT=587" \
        "EMAIL_USE_TLS=True" \
        "EMAIL_HOST_USER=${EMAIL_USER}" \
        "DEFAULT_FROM_EMAIL=TB Screening <${EMAIL_USER}>" \
        "SIGN_IN_OPEN_REGISTRATION=True" \
        "DJANGO_ALLOWED_HOSTS=${HOST}" \
        "DJANGO_CSRF_TRUSTED_ORIGINS=https://${HOST}" \
        "DJANGO_SITE_DOMAIN=${HOST}" \
    --output none

# What Azure actually assigned, rather than what was worked out above. The two
# agree, and if they ever stop agreeing this says so rather than leaving an app
# that refuses every request and an address nobody can open.
ASSIGNED="$(az containerapp show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn \
    --output tsv)"
if [ "$ASSIGNED" != "$HOST" ]; then
    echo "  It answers at ${ASSIGNED}, not the ${HOST} it was configured for," >&2
    echo "  so it will refuse every request. Put that right with:" >&2
    echo >&2
    echo "    az containerapp update --name ${APP_NAME} --resource-group ${RESOURCE_GROUP} --set-env-vars DJANGO_ALLOWED_HOSTS=${ASSIGNED} DJANGO_CSRF_TRUSTED_ORIGINS=https://${ASSIGNED} DJANGO_SITE_DOMAIN=${ASSIGNED}" >&2
    echo >&2
    exit 1
fi

say "Waiting for it to report itself ready"
# The first start pulls an image of a couple of gigabytes and then loads
# TensorFlow, so this is slow once and quick afterwards.
URL="https://${HOST}"
for attempt in $(seq 1 40); do
    code="$(curl -s -o /tmp/health.json -w '%{http_code}' "${URL}/health/" || true)"
    if [ "$code" = "200" ]; then
        echo "  ready after ${attempt} checks"
        cat /tmp/health.json
        echo
        break
    fi
    echo "  check ${attempt}: HTTP ${code:-no answer}"
    sleep 15
done

say "Done"
cat <<SUMMARY

  Address        ${URL}
  Health         ${URL}/health/
  Resource group ${RESOURCE_GROUP}
  Image          ${IMAGE}

  Add this to the Google OAuth client's authorised redirect URIs:

      ${URL}/accounts/google/login/callback/

  The app scales to zero when nobody is using it, so the first visit after a
  quiet period waits for it to start. Before a demonstration, keep one replica
  warm:

      az containerapp update --name ${APP_NAME} --resource-group ${RESOURCE_GROUP} --min-replicas 1

  and afterwards put it back, or it runs all month and spends the credit:

      az containerapp update --name ${APP_NAME} --resource-group ${RESOURCE_GROUP} --min-replicas 0

  To remove the whole deployment:

      az group delete --name ${RESOURCE_GROUP}

SUMMARY
