# obylonc build helper.
#
# Usage:
#   make build          # build for the current GOOS/GOARCH
#   make windows        # cross-compile windows/amd64 -> obylonc.exe
#   make windows-arm64   # cross-compile windows/arm64 -> obylonc-arm64.exe
#   make vet            # gofmt + go vet
#   make clean          # remove built binaries

VERSION := $(shell git describe --tags --always 2>/dev/null || echo dev)
COMMIT  := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
LDFLAGS := -X obylonc/cmd.Version=$(VERSION) -X obylonc/cmd.Commit=$(COMMIT)

.PHONY: build windows windows-arm64 vet clean

build:
	go build -ldflags "$(LDFLAGS)" -o obylonc .

windows:
	GOOS=windows GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o obylonc.exe .

windows-arm64:
	GOOS=windows GOARCH=arm64 go build -ldflags "$(LDFLAGS)" -o obylonc-arm64.exe .

vet:
	gofmt -l .
	go vet ./...

clean:
	rm -f obylonc obylonc.exe obylonc-arm64.exe
