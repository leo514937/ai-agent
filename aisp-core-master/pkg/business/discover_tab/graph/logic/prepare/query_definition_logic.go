package prepare

import (
	"context"
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/word/word_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: Query名词解释
type QueryDefinitionLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, *entities.QueryDefinition]
	commentClient     rpc.CommentService
	contentCoreClient rpc.ContentCoreRPC
	depth             int
	unmatchedLimit    int
}

func NewQueryDefinitionLogic(name string, config map[string]string) *QueryDefinitionLogic {
	res := &QueryDefinitionLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, *entities.QueryDefinition](name, config),
	}

	res.FillUserFunc = res.getDefinition
	res.MergeUserFunc = res.setDefinition
	res.commentClient = rpcImpl.NewCommentService()
	res.contentCoreClient = rpcImpl.NewContentCoreRPCImpl()
	res.depth = 1
	res.unmatchedLimit = 100
	return res
}

func (r *QueryDefinitionLogic) getDefinition(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) (*entities.QueryDefinition, error) {
	isEnable := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.IsEnableLogic))
	if !isEnable {
		return nil, nil
	}

	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "prepare.QueryDefinitionLogic.getDefinition")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	logger := log.WithFields(ctx, map[string]any{
		"func": "QueryDefinitionLogic.getDefinition",
	})

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", r.GetName())
		return nil, nil
	}

	startTime := time.Now().UnixMilli()
	if requestCtx.GetBizContext().GetChatExtraInfo() == nil ||
		requestCtx.GetBizContext().GetChatExtraInfo().GetSourceContent() == nil ||
		requestCtx.GetBizContext().GetChatExtraInfo().GetSourceContent().GetDocId() <= 0 {
		return nil, nil
	}

	chatExtraInfo := requestCtx.GetBizContext().GetChatExtraInfo()
	// 当前Query
	currQuery := requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent
	// 原始内容
	sourceContent := chatExtraInfo.GetSourceContent()

	queryDefinition := &entities.QueryDefinition{}
	// 处理评论实体词
	if sourceContent.GetDocType() == proto.DocType_COMMENT {
		commentRes, isOk := r.commentClient.GetComment(ctx, sourceContent.GetDocId(), r.depth)
		if isOk && commentRes.Comment != nil {
			// 拼接根内容
			if commentRes.RootComment != nil && commentRes.RootComment.CommentContent != "" {
				queryDefinition.Definition += fmt.Sprintf("%s\n", commentRes.RootComment.CommentContent)
			}
			// 拼接评论内容
			if commentRes.Comment.ParentComment != nil && commentRes.Comment.ParentComment.CommentContent != "" {
				// 如果 根内容 和 回复内容一致 则默认取其中一个
				if !strings.Contains(queryDefinition.Definition, commentRes.Comment.ParentComment.CommentContent) {
					queryDefinition.Definition += fmt.Sprintf("%s\n", commentRes.Comment.ParentComment.CommentContent)
				}
			}
			// 取原始内容表退
			if commentRes.CommentSourceContent != nil {
				queryDefinition.DocTitle = commentRes.CommentSourceContent.Title
				queryDefinition.DocType = aiContent.DocType_Comment
			}
			queryDefinition.Definition += commentRes.Comment.CommentContent
			queryDefinition.DocId = sourceContent.GetDocId()
			queryDefinition.DocTypeText = r.convert2DocTypeText(aiContent.DocType_Comment)
		}
	} else {
		// 处理其他实体词
		docType := word_util.WordDocType2DocType(sourceContent.GetDocType())
		if docType != aiContent.DocType_Unknown {
			modelContent := model.NewContentWithDocType(sourceContent.GetDocId(), docType)
			// 查询内容 url token
			contentResultMap := r.contentCoreClient.BatchGetContent(ctx, []model.Content{modelContent},
				base.ContentInfoFieldContentTitle,
				base.ContentInfoFieldContentDetail,
				base.ContentInfoFieldContentExtInfo,
				base.ContentInfoFieldContentBody)
			contentInfo, isOk := contentResultMap[modelContent]
			if isOk && contentInfo.GetContentBody() != nil {
				contentBody := contentInfo.GetContentBody().GetBody()
				contentBody, htmlErr := util.ContentFilterHtml(ctx, contentBody)
				if htmlErr != nil {
					logger.Warnf(ctx, "model:%v filter html error: %v", modelContent, htmlErr)
				} else {
					queryDefinition.Definition = util.GetSurroundingSentences(currQuery, contentBody, int(chatExtraInfo.GetMatchOrder()), r.unmatchedLimit)
					queryDefinition.DocId = sourceContent.GetDocId()
					queryDefinition.DocTitle = contentInfo.GetTitle()
					queryDefinition.DocType = docType
					queryDefinition.DocTypeText = r.convert2DocTypeText(docType)
				}

				// 如果是Answer 再去取Question的title
				if docType == aiContent.DocType_Answer {
					if contentInfo.GetExtInfo() != nil && contentInfo.GetExtInfo().GetParentInfo() != nil &&
						contentInfo.GetExtInfo().GetParentInfo().ContentID != "" {
						parentContentId := contentInfo.GetExtInfo().GetParentInfo().ContentID
						parentContentResultMap := r.contentCoreClient.BatchGetContentByContentID(ctx, []string{parentContentId}, base.ContentInfoFieldContentTitle)
						parentContentInfo, parentContentInfoIsOk := parentContentResultMap[parentContentId]
						if parentContentInfoIsOk && parentContentInfo.GetOutID() != "" && parentContentInfo.GetTitle() != "" {
							queryDefinition.DocTitle = parentContentInfo.GetTitle()
						}
					}
				}
			}
		}
	}

	// 去掉末尾换行
	queryDefinition.Definition = strings.TrimSuffix(queryDefinition.Definition, "\n")
	// 记录tracing和log
	r.saveTracing(util.GetJSONIgnoreError(queryDefinition), startTime, requestCtx)
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(queryDefinition))
	return queryDefinition, nil
}

func (r *QueryDefinitionLogic) setDefinition(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], definition *entities.QueryDefinition) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.QueryDefinitionLogic.setDefinition")
	defer span.Finish()
	logger := log.WithFields(ctx, map[string]any{
		"func": "QueryDefinitionLogic.setDefinition",
	})
	if definition == nil || definition.Definition == "" {
		return nil
	}

	logger.Infof(ctx, "definition: %+v", definition)
	requestCtx.GetBizContext().SetQueryDefinition(definition)
	return nil
}

func (r *QueryDefinitionLogic) convert2DocTypeText(docType aiContent.DocType_Type) string {
	switch docType {
	case aiContent.DocType_Article, aiContent.DocType_Answer:
		return "知乎文章"
	case aiContent.DocType_Comment:
		return "知乎回答"
	default:
		return "未知"
	}
}

func (r *QueryDefinitionLogic) saveTracing(recallOption string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicInput:  []string{},
		LogicOutput: []string{recallOption},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)
}
