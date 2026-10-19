# Container for the deployed screening application.
#
# Built in two stages. The first installs the Python dependencies, which
# includes TensorFlow and takes several minutes; the second copies the result
# into a clean image without the compilers needed to build them. The runtime
# image is smaller and carries less that could be exploited.
#
# The image contains the trained model. The deployment guidance is explicit
# that a prediction must not fetch an unspecified latest model, so the weights
# are fixed at build time and the image is the release.

FROM python:3.11-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential is needed to compile a few wheels; it does not reach the
# runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt


FROM python:3.11-slim AS runtime

# libgl1 and libglib2.0-0 are OpenCV's runtime dependencies. The headless
# build still links against them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    DJANGO_DEBUG=False \
    DJANGO_BEHIND_PROXY=True \
    TB_DATA_DIR=/tmp/tb-data

# Hugging Face Spaces run the container as uid 1000 and expose port 7860.
# Running as root would work and is not worth the risk for a web application.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --chown=app:app . .

USER app

# Collected at build time so a restart does not repeat it. SECRET_KEY is only
# needed for Django to import its settings here; the real one arrives from the
# environment at run time.
RUN DJANGO_SECRET_KEY=build-only \
    DB_NAME=build DB_USER=build DB_PASSWORD=build \
    python manage.py collectstatic --noinput

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl --fail http://localhost:7860/health/ || exit 1

ENTRYPOINT ["./deploy/entrypoint.sh"]
