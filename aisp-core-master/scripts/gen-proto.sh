#!/usr/bin/env bash

# 仅更新 proto/grpc/aisp_core/main.proto 时需要执行这个脚本，并将生成的代码提交
# TODO 待完善

go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.30.0
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.3.0
go install github.com/grpc-ecosystem/grpc-gateway/v2/protoc-gen-openapiv2@latest
go install github.com/grpc-ecosystem/grpc-gateway/v2/protoc-gen-grpc-gateway@latest

# 说明：mac 版本 和 linux 版本略有不同，但应该不影响
wget https://github.com/protocolbuffers/protobuf/releases/download/v3.11.4/protoc-3.11.4-osx-x86_64.zip
# wget https://github.com/protocolbuffers/protobuf/releases/download/v3.11.4/protoc-3.11.4-linux-x86_64.zip
unzip -d protoc protoc-3.11.4-osx-x86_64.zip