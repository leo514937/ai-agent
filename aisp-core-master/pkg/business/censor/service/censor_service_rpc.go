package service

import (
	"context"
	"strings"

	proto2 "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	proto "git.in.zhihu.com/one-rpc-go/thrift-censor/censor_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/rum_cache"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/pkg/errors"
	"github.com/spf13/cast"
)

type CensorServiceRpcImpl struct {
	wordService word_service.WordMapperService
	rumClient   rpc.RumClient[float32]
	rumCache    rum_cache.RumCache
}

func NewCensorServiceRpcImpl() *CensorServiceRpcImpl {
	return &CensorServiceRpcImpl{
		wordService: word_service.DefaultWordMapperService,
		rumClient:   rpcImpl.DefaultFloat32RumClientImpl,
		rumCache:    rum_cache.NewRumCache(),
	}
}

func (s *CensorServiceRpcImpl) GetCensorInfo(ctx context.Context, param *proto.GetCensorInfoParam) (
	r *proto.GetCensorInfoResp, err error) {
	if param == nil {
		return nil, errors.Errorf("param 为空")
	} else {
		log.Infof(ctx, "GetCensorInfo request:%s", util.GetJSONIgnoreError(param))
	}

	workTypeRef := macro.CensorTypeAndWordTypeRef[strings.ToLower(param.ObjectType)]
	if workTypeRef == 0 {
		return nil, errors.Errorf("无当前ObjectType类型 => %v", strings.ToLower(param.ObjectType))
	}

	wordMapper, err := s.wordService.GetSourceWordInfo(ctx, cast.ToInt64(param.ObjectID), workTypeRef)
	if err != nil {
		return nil, err
	}

	isDeleted := false
	if wordMapper.Deleted == cast.ToInt64(macro.Dict_Yes) {
		isDeleted = true
	}

	resp := proto.GetCensorInfoResp{
		ObjectID:  &param.ObjectID,
		Content:   &wordMapper.Word,
		IsDeleted: &isDeleted,
	}
	return &resp, nil
}

func (s *CensorServiceRpcImpl) SetCensorResult_(ctx context.Context, param *proto.SetCensorResultParam) (
	r *proto.SetCensorResultResp, err error) {

	if param == nil {
		return nil, errors.Errorf("param 为空")
	} else {
		log.Infof(ctx, "SetCensorResult request:%s", util.GetJSONIgnoreError(param))
	}

	// 获取操作结果
	operations := param.Operations
	if operations == nil || len(operations) == 0 {
		return nil, errors.Errorf("param => operations 为空")
	}

	for _, v := range operations {
		switch strings.ToLower((*v).Name) {
		case macro.CensorOperationRemove:
			workTypeRef := macro.CensorTypeAndWordTypeRef[strings.ToLower(param.ObjectType)]
			if workTypeRef == 0 {
				return nil, errors.Errorf("无当前ObjectType类型 => %v", strings.ToLower(param.ObjectType))
			}

			wordId, typeErr := util.String2Int64(param.ObjectID)
			if typeErr != nil {
				return nil, typeErr
			}

			flag, err := s.wordService.RemoveWordId(ctx, wordId, workTypeRef)
			if !flag {
				return nil, err
			}

			rumTable := queryType2RumTable(proto2.QueryType(workTypeRef))
			if rumTable != "" {
				// 删除 rum
				actionRes := s.rumClient.RumDelete(ctx, rumTable, wordId, "")
				if !actionRes {
					// 保存删除错误记录到 redis中 便于后期进行后过滤(只有异常情况下才会有记录)
					s.rumCache.SaveDeleteErrorCache(ctx, wordId, rumTable)
					log.Errorf(ctx, "Del PrefabWordToRum Err wordId: %d, rum del err:%v", wordId, actionRes)
				} else {
					log.Errorf(ctx, "Del PrefabWordToRum wordId: %d success", wordId)
				}
			}

			return &proto.SetCensorResultResp{}, nil
		default:
			return nil, errors.Errorf("param => operation 错误")
		}
	}
	return nil, errors.Errorf("param => operation 错误")
}

func queryType2RumTable(queryType proto2.QueryType) string {
	switch queryType {
	case proto2.QueryType_PREFAB_WORD_QUESTION,
		proto2.QueryType_PREFAB_WORD_HOT_QUESTION,
		proto2.QueryType_RELATE_WORD_HOT_EVENT:
		return macro.AiPrefabWordV3RumTable
	default:
		return ""
	}
}

var (
	_ proto.CensorService = (*CensorServiceRpcImpl)(nil)
)
