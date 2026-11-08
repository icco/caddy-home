FROM golang:1.27.3-alpine AS builder

ENV GODEBUG=netdns=cgo
ENV CGO_ENABLED=1

RUN apk add --no-cache gcc musl-dev

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go ./
RUN go build -trimpath -ldflags "-w -s" -o /usr/bin/caddy .

FROM caddy:2.11.9-alpine

LABEL org.opencontainers.image.source=https://github.com/icco/caddy-home
LABEL org.opencontainers.image.description="Caddy reverse proxy for icco's home server; custom build with caddy-docker-proxy, caddy-security, and caddy-ratelimit modules."
LABEL org.opencontainers.image.licenses=MIT

ENV CADDY_INGRESS_NETWORKS=caddy
ENV CADDY_DOCKER_CADDYFILE_PATH=/srv/Caddyfile

RUN apk upgrade --no-cache ca-certificates ca-certificates-bundle

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY ./Caddyfile /srv/Caddyfile
COPY ./themes /srv/themes

RUN OAUTH_CLIENT_ID=dummy \
    OAUTH_CLIENT_SECRET=dummy \
    OAUTH_AUTH_URL=https://example.com/auth \
    JWT_SHARED_KEY=dummy \
    caddy validate

CMD ["caddy", "docker-proxy"]
