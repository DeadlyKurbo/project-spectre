# Railway builds with this file whenever it exists at the repo root, regardless
# of the builder selected for the service.
#
# Layers are ordered so the slow step (installing dependencies) only reruns when
# requirements.txt changes. Code-only pushes reuse the cached dependency layer,
# so the build only copies the source and Railway only has to push/pull that
# small layer instead of the whole virtualenv.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Kept at /app/.venv (and first on PATH) so a custom start command set in the
# Railway dashboard, e.g. `/app/.venv/bin/python ...` or `python ...`, keeps
# working.
COPY requirements.txt .
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install -r requirements.txt

COPY . .

# Precompile the app's bytecode so the web and bot processes don't each have to
# compile every module on boot.
RUN /app/.venv/bin/python -m compileall -q -j 0 -x '/\.venv/' .

CMD ["/app/.venv/bin/python", "railway_entrypoint.py"]
