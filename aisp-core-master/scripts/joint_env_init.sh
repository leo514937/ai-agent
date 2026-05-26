#!/usr/bin/env bash

export GOPROXY=https://goproxy.cn GOPRIVATE=git.in.zhihu.com
go install golang.org/x/tools/cmd/goimports@v0.10.0
git config --global url."git@git.in.zhihu.com:".insteadOf "https://git.in.zhihu.com/"
go mod tidy