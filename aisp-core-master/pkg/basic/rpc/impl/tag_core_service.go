package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-tag-core/tag_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
)

type TagCoreServiceImpl struct {
	client *tag_core_thrift.TagCoreServiceClient
}

var DefaultTagCoreServiceImpl rpc.TagCoreService

func init() {
	DefaultTagCoreServiceImpl = NewTagCoreServiceImpl()
}

func NewTagCoreServiceImpl() *TagCoreServiceImpl {
	return &TagCoreServiceImpl{
		client: tag_core_thrift.NewTagCoreServiceClient(
			tzone.NewClient(
				"TagCoreService",
				tzone.TargetName("tag-core-service"),
				tzone.Timeout(3*time.Second),
			)),
	}
}

func (t *TagCoreServiceImpl) GetTagContents(ctx context.Context, sceneCode rpc.SceneCode, appGroupCode rpc.AppGroupCode, object *tag_core_thrift.ObjParam) ([]*tag_core_thrift.ObjectTagInfo, error) {
	param := &tag_core_thrift.GetTagParam{
		AppGroupCode: string(appGroupCode),
		SceneCode:    string(sceneCode),
		ObjParam:     object,
	}
	return t.client.GetTagContents(ctx, param)
}

func (t *TagCoreServiceImpl) MGetTagContents(ctx context.Context, sceneCode rpc.SceneCode, appGroupCode rpc.AppGroupCode, objects []*tag_core_thrift.ObjParam) (map[*tag_core_thrift.ObjectInfo][]*tag_core_thrift.ObjectTagInfo, error) {
	param := make([]*tag_core_thrift.GetTagParam, 0)
	for _, v := range objects {
		param = append(param, &tag_core_thrift.GetTagParam{
			AppGroupCode: string(appGroupCode),
			SceneCode:    string(sceneCode),
			ObjParam:     v,
		})
	}
	return t.client.MGetTagContents(ctx, param)
}
