FROM golang:1.22-alpine AS builder

WORKDIR /src

ENV GOSUMDB=off

RUN apk add --no-cache git ca-certificates tzdata

COPY go.mod go.sum ./
RUN /usr/local/go/bin/go mod download

COPY . .

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 /usr/local/go/bin/go build -o /out/chirpstack-simulator .

FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata

WORKDIR /app

COPY --from=builder /out/chirpstack-simulator /usr/local/bin/chirpstack-simulator

CMD ["/usr/local/bin/chirpstack-simulator", "-c", "/app/chirpstack-simulator.toml"]
