# syntax=docker/dockerfile:1
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/agentmesh-control-plane ./cmd/server \
 && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/agentmesh-migrate ./cmd/migrate

FROM alpine:3.21
RUN apk add --no-cache ca-certificates tzdata && addgroup -S agentmesh && adduser -S agentmesh -G agentmesh
WORKDIR /app
COPY --from=build /out/agentmesh-control-plane /app/agentmesh-control-plane
COPY --from=build /out/agentmesh-migrate /app/agentmesh-migrate
RUN mkdir -p /app/data/knowledge && chown -R agentmesh:agentmesh /app
USER agentmesh
EXPOSE 8086
CMD ["/app/agentmesh-control-plane"]
