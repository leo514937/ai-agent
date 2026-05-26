#!/usr/bin/env bash


SELF_DIR=$(cd "$(dirname "$0")" || exit;pwd)

echo "project_dir: ${SELF_DIR}"

cd "${SELF_DIR}" || exit 1

pwd

# ======================= 准备 golang 环境 =======================

make fmt

if ! bash scripts/inspect.sh
then
    echo "inspect failed"
    exit 1
fi

make -j2