package rpc

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-tag-core/tag_core_thrift"
)

type TagCoreService interface {
	GetTagContents(ctx context.Context, sceneCode SceneCode, appGroupCode AppGroupCode, object *tag_core_thrift.ObjParam) ([]*tag_core_thrift.ObjectTagInfo, error)
	MGetTagContents(ctx context.Context, sceneCode SceneCode, appGroupCode AppGroupCode, objects []*tag_core_thrift.ObjParam) (map[*tag_core_thrift.ObjectInfo][]*tag_core_thrift.ObjectTagInfo, error)
}
