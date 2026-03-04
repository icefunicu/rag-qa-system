FROM golang:1.25-bookworm AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/go-api ./cmd/server

FROM gcr.io/distroless/static-debian12
COPY --from=builder /out/go-api /go-api
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/go-api"]

