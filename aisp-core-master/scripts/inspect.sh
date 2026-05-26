#!/usr/bin/env bash

echo "BUILD_TYPE=${BUILD_TYPE}"
if [[ ${BUILD_TYPE} = "master" ]]; then
  exit 0   # mr 阶段已经检测过了， master 阶段可以跳过
fi

SELF_DIR=$(cd "$(dirname "$0")"/.. || exit;pwd)

cd "${SELF_DIR}" || exit 1

go mod tidy
if [ "$(git status | grep -E "\.go$|go.mod" -c)" -ne 0 ];then
  # 检测 build 后是否有新的变更产生，解决这个的问题是，make fmt 后，再提交。如果是本地执行，需要保证所有 diff 均提交
  git status
  echo "please, run [ make fmt ], and try again"

  exit 1
else
  echo "ok"
fi

GOLANGCI_LINT_VERSION=$(golangci-lint --version 2> /dev/null)
expect_golangci_lint_version="golangci-lint has version v1.64.8"
if ! [[ "${GOLANGCI_LINT_VERSION}" =~ ${expect_golangci_lint_version} ]] ; then
  go install github.com/golangci/golangci-lint/cmd/golangci-lint@v1.64.8
fi
golangci-lint --version

echo "depend ready"
pwd
cd "${SELF_DIR}" || exit 1
pwd

#很费时，不建议使用，扫描时间在小时级别
function check_all() {
  error_num=0
  for dir in $(find "${SELF_DIR}" -type d | grep -v bin | grep -v docs | grep -v gen-go | grep -v resources | grep -v script | \
    grep -v thrift_files |grep -v protos | grep -v pkg | grep -v .git | grep -v .idea | grep -v tools); do
        echo "inspect: $dir"
        len=$(find "$dir" -maxdepth 1 -name "*.go" | wc -l)
        if [ "$len" -ge 1 ] && ! golangci-lint run -j 5 --fix "$dir"; then
          echo "golangci-lint $dir failed, try again"
          ((error_num++))
        fi
  done
  return 0
}

# 仅对比当前分支提交的和 master 主分支的区别，只检查被修改文件
function check_modify() {
  BRANCH_NAME=$(git rev-parse --abbrev-ref --symbolic-full-name @\{push\})
  REMOTE_NAME=$(echo "${BRANCH_NAME}" | awk -F'/' '{print $1}')
  echo "开发分支检查完毕，开发分支的远端分支为：'${BRANCH_NAME}'"
  error_num=0
  GIT_VERSION=$(git version)
  GIT_REQ_VERSION="git version 2.17.0"
  if [[ ${GIT_VERSION} < ${GIT_REQ_VERSION} ]];then
      echo "${GIT_VERSION} less than 2.17.0, please upgrade git version first"
      exit 1
  fi
  branch=$(git branch --show-current)
  remote=$(git remote -v | grep "data/zrec" | head -1 | awk -F' ' '{print $1}')
  if ! git pull --rebase "${remote}" master &> /dev/null ; then
    git rebase --abort &> /dev/null
    echo "本地有未提交的修改或者与线上代码产生冲突, 请先提交代码或者解决冲突后重新执行「make inspect」"
    exit 1
  fi
  for dir in $(git diff "${remote}/master...${branch}" --name-only | xargs -I {} dirname {} | \
    sort -u | grep -v bin | grep -v docs | grep -v gen-go | grep -v resources | grep -v script | \
    grep -v thrift_files | grep -v protos | grep -v pkg | grep -v .git | grep -v .idea | grep -v tools); do
      if [ ! -e "${dir}" ]; then # -e 可以判断文件或者目录是否存在
        echo "golangci-lint skip removed directory: ${dir}"
        continue
      fi
      echo "inspect: $dir"
      len=$(find "$dir" -maxdepth 1 -name "*.go" | wc -l)
      # 本地 inspect 提供自动修复功能，这一功能仅针对于支持自动修复的 linter。自动修复后可以检查一下修复的代码是否正确，然后再 push 一次，否则 mr 构建时仍然会报错
      if [ "$len" -ge 1 ] && ! golangci-lint run -j 5 --fix "$dir"; then
          echo "golangci-lint $dir failed, try again"
          ((error_num++))
      fi
  done
  if [ "${error_num}" -ne 0 ]; then
    echo "${error_num} errors were found by golangci-lint, please modify"
  fi
  return 0
}

check_lint() {

  echo "run golangci-lint"

  if [ -n "${DIFF_FILES_GO}" ];then
    echo "lint changed files:" "${DIFF_FILES_GO}"

    for dir in $(echo "${DIFF_FILES_GO}" | tr ',' '\n' | xargs dirname | sort -u | grep -v "gen-go/" | \
        grep -v "thrift_files/" | grep -v "pkg/" | grep -v "tools"); do
      if [ ! -e "${dir}" ]; then # -e 可以判断文件或者目录是否存在
        echo "golangci-lint skip removed directory: ${dir}"
        continue
      fi
      echo "golangci-lint:" "${dir}"
      len=$(find "$dir" -maxdepth 1 -name "*.go" | wc -l)
      if [ "$len" -ge 1 ] && ! golangci-lint run "$dir"; then
        echo "golangci-lint ${dir} failed, try again"
        return 1
      fi
    done

    echo "lint changed files done"
  else
    if [ -n "${ARTIFACT_TAG}" ];then
      # 说明在 ci 环境，没有 go 文件修改
      return 0
    fi
    # check_modify
  fi
	return 0
}

# try 2 times
if ! check_lint; then
  echo "check_lint failed, try again"
  if ! check_lint; then
      echo "check_lint failed"
      echo "please, run [ make inspect ], and try again"
      exit 1
  fi
fi

