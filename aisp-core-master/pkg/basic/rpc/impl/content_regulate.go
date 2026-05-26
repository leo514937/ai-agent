package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	regulate "git.in.zhihu.com/one-rpc-go/thrift-content-regulate-core/content_regulate_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

type ContentRegulateRPCImpl struct {
	contentRegulateCoreClient *regulate.ContentRegulateCoreServiceClient
	batchSize                 int
}

var DefaultContentRegulateRPCImpl rpc.ContentRegulateRPC

func init() {
	DefaultContentRegulateRPCImpl = NewContentRegulateRPCImpl()
}

func NewContentRegulateRPCImpl() *ContentRegulateRPCImpl {
	return NewContentRegulateRPCImplWithBatchSize(50)
}

func NewContentRegulateRPCImplWithBatchSize(batchSize int) *ContentRegulateRPCImpl {
	contentRegulateCoreClient := tzone.NewClient(
		"ContentRegulateCoreService",
		tzone.TargetName("content-regulate-core-rpc"),
		tzone.Timeout(200*time.Millisecond),
	)

	return &ContentRegulateRPCImpl{
		contentRegulateCoreClient: regulate.NewContentRegulateCoreServiceClient(contentRegulateCoreClient),
		batchSize:                 batchSize,
	}
}

func (r *ContentRegulateRPCImpl) BatchGetValidInstruction(ctx context.Context, sceneCode string, subSceneCode string, allKeys []model.Content) map[model.Content]map[string]string {
	res := make(map[model.Content]map[string]string)

	// 默认子场景 code
	if subSceneCode == "" {
		subSceneCode = rpc.SubSceneCodeDEFAULT
	}
	// 分窗口进行 rpc 调用
	groupGetFunc := func(ids interface{}) interface{} {
		return r.batchGetValidInstruction(ctx, sceneCode, subSceneCode, ids.([]model.Content))
	}
	safe_group.BatchGet(r.batchSize, allKeys, groupGetFunc, &res)

	return res
}

func (r *ContentRegulateRPCImpl) batchGetValidInstruction(ctx context.Context, sceneCode string, subSceneCode string, contents []model.Content) map[model.Content]map[string]string {
	result := make(map[model.Content]map[string]string, len(contents))

	runFunc := func(ctx context.Context) error {
		// 转换成管控接口要求的 content 格式
		objectInfos := contents2ObjectInfos(contents)
		if len(objectInfos) == 0 {
			return nil
		}

		request := &regulate.BatchGetInstructionParam{
			SceneCode:    sceneCode,
			SubSceneCode: &subSceneCode,
			ObjectInfos:  objectInfos,
		}
		response, err := r.contentRegulateCoreClient.BatchGetValidInstruction(ctx, request)

		if err != nil || response == nil {
			return err
		}
		if response.GetError() != nil {
			return response.GetError()
		}

		for _, info := range response.GetContentInstructionInfos() {
			docType, exist := rpc.RegulateContentTypeRevertMap[info.GetType()]
			contentId, _ := util.String2Int64(info.GetOutID())
			if !exist || contentId <= 0 {
				continue
			}
			result[model.Content{ContentID: contentId, ContentType: docType}] = info.GetInstructionMap()
		}
		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

func contents2ObjectInfos(contents []model.Content) []*regulate.ObjectInfo {
	objectInfos := make([]*regulate.ObjectInfo, 0, len(contents))
	for _, key := range contents {
		objectType, objectTypeExist := rpc.RegulateContentTypeMap[key.ContentType]
		if !objectTypeExist {
			continue
		}
		if key.ContentID <= 0 {
			continue
		}
		objectInfos = append(objectInfos, &regulate.ObjectInfo{
			Type:  objectType,
			OutID: util.Int64String(key.ContentID),
		})
	}

	return objectInfos
}

var _ rpc.ContentRegulateRPC = (*ContentRegulateRPCImpl)(nil)
