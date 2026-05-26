package security_post

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

func updateDialogCache(
	isSecurityPassed bool,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	itemList []*data_frame.ItemData[entities.Item]) *model.DialogRecord {
	var answerDialog *model.DialogRecord
	// 如果安全没过 unPass
	if !isSecurityPassed {
		for _, item := range itemList {
			currentDialogue := requestCtx.GetBizContext().GetCurrentDialogue()
			if currentDialogue.Query == nil {
				continue
			}
			respType := item.GetBizItem().ChatRespType
			createType := model.DialogCreateTypeLLM
			errorType := model.DialogErrorTypeUnknown
			switch respType {
			case proto.ChatRespType_REFUSE:
				errorType = model.DialogErrorTypeSecurityRejection
			case proto.ChatRespType_RED_LINE:
				errorType = model.DialogErrorTypeRedLine
				createType = model.DialogCreateTypeStaticLib
			case proto.ChatRespType_FAQ:
				errorType = model.DialogErrorTypeFaq
				createType = model.DialogCreateTypeStaticLib
			default:
				errorType = model.DialogErrorTypeUnknown
			}

			switch item.GetBizItem().ChatTextTurnoverType {
			case entities.ChatMappingTypeLLMAnswer:
				currentDialogue.Query.ErrorType = errorType.ToConvert()
				// 创建answer dialog
				answerDialog = entities.NewAnswerDialogFormProtoChatRequest(
					requestCtx.GetBizContext(), item.GetBizItem().Text, createType, errorType)
			case entities.ChatMappingTypeQuery:
				currentDialogue.Query.ErrorType = errorType.ToConvert()
			default:
			}
		}
	}
	return answerDialog
}
