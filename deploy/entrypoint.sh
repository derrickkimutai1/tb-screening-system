#!/bin/sh
# Start the deployed application.
#
# Migrations run here rather than in the image build, because the build has no
# database to reach. Running them on start means a redeploy brings the schema
# forward without a separate manual step, which is what keeps the deployed
# schema traceable to the commit that is running.
set -e

echo "applying migrations"
python manage.py migrate --noinput

# One worker. The model is held in memory per process and is most of the
# container's footprint, so a second worker would double it for no benefit on
# the single CPU a free Space provides. Threads let a slow request, such as a
# first prediction that loads the model, avoid blocking a health check.
#
# The timeout is generous because the first prediction after a cold start loads
# TensorFlow and the weights, which takes a few seconds.
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:"${PORT:-7860}" \
    --workers 1 \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile -
