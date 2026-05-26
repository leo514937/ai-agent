#!/usr/bin/env bash

export GOPROXY=https://goproxy.cn GOPRIVATE=git.in.zhihu.com
go install golang.org/x/tools/cmd/goimports@v0.10.0
git config --global url."git@git.in.zhihu.com:".insteadOf "https://git.in.zhihu.com/"


# 编译 delve 工具
cd /data/apps
git clone git@git.in.zhihu.com:ai/delve.git
cd /data/apps/delve/cmd/dlv/
go build
go install

# 指定搜索路径
search_path="/data/apps"
# 搜索包含"aisp"的文件夹，并获取第一个匹配的文件夹名称
aisp_path=$(find "$search_path" -type d -name "*aisp-core*" | head -n 1)
# 获取本容器IP地址
ip=$(ifconfig eth0 | grep 'inet ' | awk '{ print $2 }')

## 服务端启动命令
echo "本POD容器，执行命令："
echo -e "cd $aisp_path\ndlv debug --headless --listen=:10110 --api-version=2 --accept-multiclient $aisp_path/cmd/main.go -- grpc-service"
echo ""
## 跳板机启动命令
echo "跳板机执行名称："
echo "ssh -vCNg -L  10110:$ip:10110  root@$ip -p 22"
