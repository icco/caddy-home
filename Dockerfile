# https://github.com/caddyserver/caddy/releases
ARG CADDY_VERSION=2.8.4
FROM caddy:${CADDY_VERSION}-builder AS builder

ENV GODEBUG=netdns=cgo
ENV CGO_ENABLED=1

RUN apk add --no-cache gcc musl-dev

RUN xcaddy build ${CADDY_VERSION} \
    --with github.com/lucaslorentz/caddy-docker-proxy/v2 \
    --with github.com/greenpau/caddy-security

FROM caddy:${CADDY_VERSION}-alpine

ENV CADDY_INGRESS_NETWORKS=caddy
ENV CADDY_DOCKER_CADDYFILE_PATH=/Caddyfile

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY ./Caddyfile /Caddyfile

CMD ["caddy", "docker-proxy"]
