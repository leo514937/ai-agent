package impl

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

var (
	_                  rpc.TagCoreGRPC = (*TagCoreGrpcImpl)(nil)
	DefaultTagGrpcImpl *TagCoreGrpcImpl
)

func init() {
	DefaultTagGrpcImpl = NewTagCoreGrpcImpl()
}

type TagCoreGrpcImpl struct {
	timeout   time.Duration
	batchSize int
	client    tag_core.TagServiceClient
}

func NewTagCoreGrpcImpl() *TagCoreGrpcImpl {
	clientConn, err := grpc.DialContext(context.Background(), "tag-core-grpc-service")
	if err != nil {
		log.Errorf(context.Background(), "dial tag-core-grpc-service failed. err: %+v", err)

		panic(err)
	}

	return &TagCoreGrpcImpl{
		client:    tag_core.NewTagServiceClient(clientConn),
		timeout:   250 * time.Millisecond,
		batchSize: 50,
	}
}

func (r *TagCoreGrpcImpl) BatchGetTag(ctx context.Context, sceneCode rpc.SceneCode, appGroupCode rpc.AppGroupCode, itemKeys []model.Content) map[model.Content]*tag_core.ObjectProfile {
	itemKeys = lo.UniqBy(itemKeys, func(item model.Content) string {
		return item.String()
	})
	res := make(map[model.Content]*tag_core.ObjectProfile)
	safe_group.BatchGet(r.batchSize, itemKeys, func(itemKeys interface{}) interface{} {
		return r.batchGetTag(ctx, sceneCode, appGroupCode, itemKeys.([]model.Content))
	}, &res)
	return res
}

func (r *TagCoreGrpcImpl) batchGetTag(ctx context.Context, sceneCode rpc.SceneCode, appGroupCode rpc.AppGroupCode, itemKeys []model.Content) map[model.Content]*tag_core.ObjectProfile {
	res := make(map[model.Content]*tag_core.ObjectProfile, len(itemKeys))

	var objParams []*tag_core.ObjParams
	var contentKeyMap = make(map[string]model.Content, len(itemKeys))

	for _, itemKey := range itemKeys {
		objType := rpc.DocTypeToObjType(itemKey.ContentType)
		objId := util.Int64String(itemKey.ContentID)
		if itemKey.ContentID == 0 && itemKey.URLToken != "" {
			objId = itemKey.URLToken
		}
		objParams = append(objParams, &tag_core.ObjParams{ObjID: objId, ObjType: objType})
		contentKeyMap[fmt.Sprintf("%d_%s", objType, objId)] = itemKey
	}

	rpcFunc := func(ctx context.Context) error {
		batchGetUserRequest := tag_core.BatchGetTagRequest{
			ObjParams:    objParams,
			SceneCode:    string(sceneCode),
			AppGroupCode: string(appGroupCode),
		}

		newCtx, cancel := context.WithTimeout(ctx, r.timeout)
		defer cancel()
		objectProfiles, err := r.client.BatchGetTag(newCtx, &batchGetUserRequest)
		if err == nil {
			for _, objectProfile := range objectProfiles.GetProfile() {
				objType := objectProfile.GetObjIdentity().GetObjType()
				objId := util.Int64String(objectProfile.GetObjIdentity().GetId())
				if objId == "0" || objId == "" && objectProfile.GetObjIdentity().GetIdString() != "" {
					objId = objectProfile.GetObjIdentity().GetIdString()
				}
				if itemKey, exist := contentKeyMap[fmt.Sprintf("%d_%s", objType, objId)]; exist {
					res[itemKey] = objectProfile
				}
			}
		}
		return err
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, rpcFunc)

	return res
}
