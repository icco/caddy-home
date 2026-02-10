# https://github.com/caddyserver/caddy/releases
ARG CADDY_VERSION=2.10.2
FROM caddy:${CADDY_VERSION}-builder AS builder

ENV GODEBUG=netdns=cgo
ENV CGO_ENABLED=1

RUN apk add --no-cache gcc musl-dev

# https://github.com/lucaslorentz/caddy-docker-proxy/releases
# https://github.com/greenpau/caddy-security/releases
# https://github.com/mholt/caddy-ratelimit/releases
RUN xcaddy build ${CADDY_VERSION} \
    --with github.com/lucaslorentz/caddy-docker-proxy/v2@v2.10.0 \
    --with github.com/greenpau/caddy-security@v1.1.31 \
    --with github.com/mholt/caddy-ratelimit

FROM caddy:${CADDY_VERSION}-alpine

ENV CADDY_INGRESS_NETWORKS=caddy
ENV CADDY_DOCKER_CADDYFILE_PATH=/srv/Caddyfile

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY ./Caddyfile /srv/Caddyfile
COPY ./themes /srv/themes

# RUN caddy validate

CMD ["caddy", "docker-proxy"]
