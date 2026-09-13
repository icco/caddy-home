# AGENTS.md

Guidance for coding agents working on caddy-home.

## Project Overview

Caddy configuration and Docker container setup acting as the edge reverse proxy for home network services.

## Commands

```sh
caddy fmt --overwrite Caddyfile   # Format Caddyfile
caddy validate --config Caddyfile # Validate Caddy syntax
docker build -t caddy-home .      # Build container image
```

## Architecture & Layout

- `Caddyfile` — Main Caddy reverse proxy rules, upstream routes, and domain configurations.
- `Dockerfile` / `docker-compose.yml` — Containerization setup for deploying Caddy.

## Conventions

- PR titles and commits must follow Conventional Commits with lowercase subjects.
- Always validate the Caddyfile syntax before submitting changes.
- Never commit private internal credentials or plaintext tokens.
