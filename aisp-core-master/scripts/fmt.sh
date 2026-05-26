#!/usr/bin/env bash

SELF_DIR=$(dirname "$0")
cd "${SELF_DIR}"/.. || exit


if [ "$(uname)" = "Darwin" ]; then
  if ! which gsed ; then
    # mac 下 如果没有 gsed，可以通过 brew install gnu-sed 来安装
    echo "no install gsed, please run: brew install gnu-sed"
    exit 1
  fi
fi

if ! which goimports ; then
  if [ "$(uname)" = "Darwin" ]; then
    # 因为 goimports 命令不能查看版本，所以 mac 电脑上直接安装一下项目中可以使用 goimports 的版本，避免有的机器安装的版本与项目指明的不统一
    go install golang.org/x/tools/cmd/goimports@v0.10.0
  else
    # 默认 goimports 为 go 1.10 版本的太低了
    GOIMPORT_PATH=$(which goimports)
    if [ "${GOIMPORT_PATH}" == "/usr/bin/goimports" ] ; then
      go install golang.org/x/tools/cmd/goimports@v0.10.0
    fi
  fi
fi

bash scripts/fmt_imports.sh ./pkg
bash scripts/fmt_imports.sh ./cmd

go fmt ./pkg/... ./cmd/...