package util

import (
	"context"

	"git.in.zhihu.com/go/base/telemetry/log"
	"github.com/gogo/protobuf/proto"
	"github.com/golang/protobuf/jsonpb"
	goProto "github.com/golang/protobuf/proto" // nolint //whyNotLint: temporary use
)

func GoProtoUnmarshal(src []byte, dst proto.Message) error {
	if dst == nil || src == nil {
		return nil
	}
	return goProto.Unmarshal(src, dst)
}

func GoProtoClone(src proto.Message) proto.Message {
	return proto.Clone(src)
}

// ProtoUnmarshalMerge
// 将data数据设置到dst对象中
// 如果dst对象的字段已经有值 而data数据中没有对应字段的值则不会修改这个字段
func ProtoUnmarshalMerge(dst proto.Message, data []byte) error {
	return proto.UnmarshalMerge(data, dst)
}

// ProtoUnmarshal
// 生成新的对象指向dst变量 并将data数据设置到dst对象中
func ProtoUnmarshal(dst proto.Message, data []byte) error {
	return proto.Unmarshal(data, dst)
}

// ProtoMarshal 大部分时候错误都不关心，所以在架构做 err 封装，会打印错误日志
// 如果需要处理错误，直接调用 proto.Marshal 即可
func ProtoMarshal(src proto.Message) []byte {
	marshal, err := proto.Marshal(src)
	if err != nil {
		log.Errorf(context.Background(), "ProtoMarshal err:%v", err)
	}
	return marshal
}

// ProtoMarshalEmitDefaults proto 进行 json 序列化，会序列化所有字段，包括默认值 0 null 等
func ProtoMarshalEmitDefaults(src proto.Message) string {
	pbMarshaler := &jsonpb.Marshaler{EmitDefaults: true, OrigName: true}
	result, _ := pbMarshaler.MarshalToString(src)
	return result
}
