# Agente de Jenkins: Python 3.14 + uv 0.13.8 + zsh (el vídeo final se lanza
# con /bin/zsh -f, como en el Mac del estudio, y los tests lo usan).
FROM python:3.14.10-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /usr/local/bin/

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends zsh \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios con el mismo uid que el de Jenkins (1000).
RUN useradd --create-home --uid 1000 ci
USER ci
