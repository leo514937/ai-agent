
all: inspect main corn_job_main

BUILD = go build
PROTOC = protoc
TEST = go test

export GOLANG_PROTOBUF_REGISTRATION_CONFLICT = ignore

main:
	$(BUILD) -o bin/main cmd/main.go

corn_job_main:
	$(BUILD) -o bin/cron_job_main cmd/cron-job-main/main.go

test: mock
	$(TEST) -coverprofile=coverage.out ./pkg/...

mock:
	go generate ./pkg/...

proto_zhihu:
	mkdir -p gen-go/grpc/zhihu
	$(PROTOC) \
		-Iproto/grpc/aisp_core \
		--proto_path=protoc/include \
		--go-grpc_out=gen-go/grpc/zhihu \
		--go_out=gen-go/grpc/zhihu \
		--grpc-gateway_out=gen-go/grpc/zhihu \
		--grpc-gateway_opt logtostderr=true \
		proto/grpc/aisp_core/main.proto

fmt:
	bash scripts/fmt.sh

inspect:
	bash scripts/inspect.sh
