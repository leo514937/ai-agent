package mapping

import (
	"context"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_biz_ext/paper_biz_ext"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type tracingSpecifiedDocType string

const (
	singleDoc    tracingSpecifiedDocType = "singleDoc"
	bigSingleDoc tracingSpecifiedDocType = "bigSingleDoc"
	multDoc      tracingSpecifiedDocType = "multDoc"
)

// SpecifiedDocOverwriteConfigLogic 单篇/多篇 覆盖config逻辑。现在实现了被agent覆盖config，后续可以扩展到通过ab覆盖config
type SpecifiedDocOverwriteConfigLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	singleSpecifiedDocMaxLen int
}

func NewSpecifiedDocOverwriteConfigLogic(name string, config map[string]string) *SpecifiedDocOverwriteConfigLogic {
	res := &SpecifiedDocOverwriteConfigLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.singleSpecifiedDocMaxLen = 10000
	res.MappingFunc = res.overwriteConfig
	return res
}

func (l *SpecifiedDocOverwriteConfigLogic) overwriteConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "mapping.SpecifiedDocOverwriteConfigLogic.overwriteConfig")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	startTime := time.Now().UnixMilli()
	var overwriteConfigMap = make(map[string]map[string]string)
	recallItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})

	// 判断单篇是否出角标
	// 1. 用户上传非pdf不出角标
	// 2. arxiv单篇模式下不出角标
	// 3. app 端不出角标
	if len(recallItems) == 1 {
		isDisableReferences := l.isSingleDocDisableReferences(recallItems[0].GetBizItem().GetItemMeta(), requestCtx.GetBizContext().GetClientSource())
		if isDisableReferences {
			addMapValue(overwriteConfigMap, stream_chat_default_tab_conf.StreamChatLogic, conf.StreamChatDisableReferences, cast.ToString(isDisableReferences))
		}
	}

	// 单篇多篇模式下不出相关追问
	addMapValue(overwriteConfigMap, stream_chat_default_tab_conf.ChatLogic, conf.ChatDisable, "true")

	// 配置变更
	var specifiedDocType tracingSpecifiedDocType
	if len(recallItems) > 1 {
		specifiedDocType = multDoc
	} else if util.UnicodeLen(recallItems[0].GetBizItem().GetItemMeta().Content) < l.singleSpecifiedDocMaxLen {
		specifiedDocType = singleDoc
	} else {
		specifiedDocType = bigSingleDoc
	}

	// 深度思考模式单篇多篇配置，更换参考文献最大 token 数限制，针对单篇使用 page 角标
	if requestCtx.GetBizContext().GetChatStyle() == proto.ChatStyle_DEEP_THINKING {
		switch specifiedDocType {
		case multDoc:
			overwriteConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic] = stream_chat_default_tab_conf.Recall2ModelChunkR1Size
		case singleDoc:
			overwriteConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic] = stream_chat_default_tab_conf.Recall2ModelChunkSmallSingleR1Size
			addMapValue(overwriteConfigMap, stream_chat_default_tab_conf.StreamChatLogic, conf.StreamChatIsCitePage, "true")
		case bigSingleDoc:
			overwriteConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic] = stream_chat_default_tab_conf.Recall2ModelChunkR1Size
			addMapValue(overwriteConfigMap, stream_chat_default_tab_conf.StreamChatLogic, conf.StreamChatIsCitePage, "true")
		}
	} else {
		switch specifiedDocType {
		case multDoc:
			overwriteConfigMap = stream_chat_default_tab_conf.SpecifiedMultDocOverwriteLogicConfigMapByPro
		case singleDoc:
			overwriteConfigMap = stream_chat_default_tab_conf.SpecifiedSingleDocOverwriteLogicConfigMapByPro
		case bigSingleDoc:
			overwriteConfigMap = stream_chat_default_tab_conf.SpecifiedBigSingleDocOverwriteLogicConfigMapByPro
		}
	}

	l.overwriteLogicConfig(requestCtx, overwriteConfigMap)

	l.saveTracing("", util.GetJSONIgnoreError(map[string]any{"SpecifiedDocType": specifiedDocType}), startTime, requestCtx)

	return items, nil
}

func addMapValue(m map[string]map[string]string, logicName string, key string, value string) {
	if m[logicName] == nil {
		m[logicName] = make(map[string]string)
	}
	m[logicName][key] = value
}

func (l *SpecifiedDocOverwriteConfigLogic) isSingleDocDisableReferences(itemMeta *model.ItemMeta, clientSource proto.ClientSource) bool {
	// 专业版直答 单篇模式下 app端不出角标
	if proto.ClientSource_ZHIHU_APP == clientSource {
		return true
	}

	// 修改角标配置 如果是非PDF 则不出角标
	if itemMeta.DocType == aiContent.DocType_Paper {
		// 修改角标配置 如果是非PDF 则不出角标
		if itemMeta.ContentInfo != nil &&
			itemMeta.ContentInfo.GetBizExtDetail() != nil &&
			itemMeta.ContentInfo.GetBizExtDetail().GetPaperBizExt() != nil {
			// arxiv 禁用单篇角标
			if paper_biz_ext.PaperPublishSource_Arxiv == itemMeta.ContentInfo.GetBizExtDetail().GetPaperBizExt().GetSource() {
				return true
			}
		}
	} else if itemMeta.DocType == aiContent.DocType_ZhiDaUserUpload {
		// 修改角标配置 如果是非PDF 则不出角标
		if itemMeta.ContentInfo != nil &&
			itemMeta.ContentInfo.GetBizExtDetail() != nil &&
			itemMeta.ContentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt() != nil {
			// fileType + fileSubType
			fileAllType := strings.ToLower(itemMeta.ContentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileType() + itemMeta.ContentInfo.GetBizExtDetail().GetZhidaUserUploadBizExt().GetFileSubType())
			if !strings.Contains(fileAllType, "pdf") {
				return true
			}
		}
	}
	return false
}

func (l *SpecifiedDocOverwriteConfigLogic) overwriteLogicConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	overwriteConfigMap map[string]map[string]string) {
	requestCtx.GetBizContext().SetLogicConfigMap(overwriteConfigMap)
}

func (l *SpecifiedDocOverwriteConfigLogic) saveTracing(input string, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   l.GetName(),
		LogicInput:  []string{input},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(l.GetName(), logicTracing)
}
