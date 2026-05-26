#!/usr/bin/env bash

SELF_DIR=$(cd $(dirname $0);pwd)
cd ${SELF_DIR}

SNAPSHOT=""
#SNAPSHOT="-SNAPSHOT"  # 如果需要打 snapshot 包则打开这条注释

if [[ ${SNAPSHOT} = "" ]]; then
    echo -e "\033[31m严禁打包非最新 master 分析的代码，请确认当前拉取了最新的代码，并处于 master 分枝 ！！！输入 [Y] 继续发布, [n] 取消\033[0m"
    read ans
    while [[ "x"${ans} != "xY" && "x"${ans} != "xn" && "x"${ans} != "xN" ]]
    do
        echo "输入 [Y/n]"
        read ans
    done

    if [ ${ans} != "Y" ] ; then
        exit 1
    fi

    echo "3"
    sleep 1
    echo "2"
    sleep 1
    echo "1"
    sleep 1
fi

PROTO_ROOT="${SELF_DIR}/../../proto/grpc"
for SERVICE_DIR in ${PROTO_ROOT}/*; do
    [ -d "$SERVICE_DIR" ] || continue
    SERVICE_NAME=$(basename "$SERVICE_DIR")
    PY_PKG=aisp_proto_${SERVICE_NAME}
    echo "==== 部署 $SERVICE_NAME ===="

    # 创建临时工作目录
    WORK_DIR="${SELF_DIR}/tmp_${SERVICE_NAME}"
    rm -rf "$WORK_DIR"
    mkdir -p "$WORK_DIR/${PY_PKG}"

    # 拷贝 proto 文件
    cp -r "$SERVICE_DIR"/* "$WORK_DIR/"

    # 如果 SERVICE_NAME 为 aisp_core_service，则需要下载 google api proto 文件
    if [ "$SERVICE_NAME" = "aisp_core_service" ]; then
        mkdir -p "$WORK_DIR/google/api"
        curl -sSfL -o "$WORK_DIR/google/api/http.proto" \
            https://raw.githubusercontent.com/googleapis/googleapis/master/google/api/http.proto
        curl -sSfL -o "$WORK_DIR/google/api/annotations.proto" \
            https://raw.githubusercontent.com/googleapis/googleapis/master/google/api/annotations.proto
    fi

    # 编译 proto 为 python
    for d in `find $WORK_DIR -name "*.proto"`; do
        protoc --proto_path=$WORK_DIR --python_out=$WORK_DIR/${PY_PKG} $d
    done

    # 拷贝 __init__.py
    find $WORK_DIR/${PY_PKG} -type d -exec cp ${SELF_DIR}/__init__.py {} \;

    # 修正 import
    find $WORK_DIR/${PY_PKG} -type f -name "*_pb2.py" -exec sed -i '' "s/\([a-zA-Z0-9]*\)\.\([a-zA-Z0-9]*\)_pb2/${PY_PKG}.\1.\2_pb2/" {} \;

    # 提取版本号
    MAIN_PROTO="$WORK_DIR/main.proto"
    if [ ! -f "$MAIN_PROTO" ]; then
        echo "$SERVICE_NAME: main.proto 文件不存在，无法提取版本号"
        rm -rf "$WORK_DIR"
        continue
    fi

    VERSION=$(grep -E "__VERSION__" "$MAIN_PROTO" | sed -E "s/.*__VERSION__.*[=: ]+['\"]([^'\"]+)['\"].*/\\1/" | head -n1)
    if [ -z "$VERSION" ]; then
        echo "$SERVICE_NAME: 未能从 main.proto 提取到版本号，请检查 __VERSION__ 的定义格式"
        rm -rf "$WORK_DIR"
        continue
    fi
    VERSION=${VERSION}${SNAPSHOT}
    echo "$SERVICE_NAME: current version: $VERSION"

    # 生成 setup.py
    cp ${SELF_DIR}/setup.py.bk $WORK_DIR/setup.py
    sed -i -e "s/<%version%>/${VERSION}/g" $WORK_DIR/setup.py
    sed -i -e "s/<%service_name%>/${SERVICE_NAME}/g" $WORK_DIR/setup.py

    # 打包上传
    cd $WORK_DIR
    python setup.py sdist upload
    cd $SELF_DIR

    # 清理
    rm -rf "$WORK_DIR"
    echo "==== $SERVICE_NAME python proto 包发布完成 ===="
done

echo "全部 python proto 包发布完成"
