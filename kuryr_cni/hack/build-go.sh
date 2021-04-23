#!/usr/bin/env bash
set -eu
cmd=kuryr-cni
eval $(go env | grep -e "GOHOSTOS" -e "GOHOSTARCH")
GOOS=${GOOS:-${GOHOSTOS}}
GOARCH=${GOACH:-${GOHOSTARCH}}
GOFLAGS=${GOFLAGS:-}
GLDFLAGS=${GLDFLAGS:-}
CGO_ENABLED=0 GOOS=${GOOS} GOARCH=${GOARCH} go build ${GOFLAGS} -ldflags "${GLDFLAGS}" -o bin/${cmd} pkg/*
