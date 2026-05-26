package querycondition

import (
	proto "git.in.zhihu.com/zhihu/aisp-core/gen-go/grpc/zhihu/aisp_core_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

func ImageSearchCondition(request *proto.SearchRequest) *model.MultiCondition {
	condition := &model.MultiCondition{
		Musts: []model.MultiCondition{
			{
				Condition: &model.Condition{
					FieldName:   macro.RuceneFieldName,
					FieldValue:  request.KnowledgeBaseName,
					OperateType: model.OperateTypeEq,
				},
			},
		},
		Shoulds: []model.MultiCondition{
			{
				Condition: &model.Condition{
					FieldName:   macro.RuceneFieldDescription,
					FieldValue:  request.Description,
					OperateType: model.OperateTypeIn,
				},
			},
		},
	}
	return condition
}
