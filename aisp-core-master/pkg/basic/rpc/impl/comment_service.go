package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-comment/comment_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func NewCommentService() rpc.CommentService {
	return &CommentServiceImpl{
		client: comment_thrift.NewCommentServiceClient(tzone.NewClient(
			"CommentService",
			tzone.TargetName("comment-service"),
			tzone.Timeout(500*time.Millisecond),
		)),
		contentClient: NewContentCoreRPCImpl(),
	}
}

type CommentServiceImpl struct {
	client        *comment_thrift.CommentServiceClient
	contentClient rpc.ContentCoreRPC
	asyncTimeout  int64
}

func (c *CommentServiceImpl) GetComment(ctx context.Context, commentId int64, depth int) (*rpc.CommentResultWrapper, bool) {
	wrapper := &rpc.CommentResultWrapper{}
	common, contentInfo, isOk := c.recursionGetCommon(ctx, &rpc.CommentResult{CommentId: commentId}, depth, 0)
	if isOk && common != nil {
		wrapper.Comment = common
		wrapper.CommentSourceContent = contentInfo

		// 获取根评论信息
		if common.RootCommentId > 0 {
			rootCommon, rootIsOk := c.getCommentAndContent(ctx, &rpc.CommentResult{CommentId: common.RootCommentId}, true)
			if rootIsOk && rootCommon != nil {
				wrapper.RootComment = rootCommon.comment
				wrapper.RootCommentSourceContent = rootCommon.content
			}
		}
		return wrapper, isOk
	}
	return wrapper, false
}

func (c *CommentServiceImpl) recursionGetCommon(ctx context.Context,
	currComment *rpc.CommentResult,
	depth int,
	order int) (*rpc.CommentResult, *rpc.CommentSourceContent, bool) {
	if depth >= 0 && (order >= depth+1) {
		return nil, nil, false
	}

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "rpc.GetCommon",
	})

	isGetContent := false
	if order == 0 {
		isGetContent = true
	}

	commentAndContent, isOk := c.getCommentAndContent(ctx, currComment, isGetContent)
	if !isOk {
		logger.Warnf(ctx, "getCommentAndContent is not ok , comment:%+v", currComment)
		return currComment, nil, false
	}

	contentInfo := commentAndContent.content
	// 处理数据
	if commentAndContent.comment != nil && commentAndContent.comment.CommentId > 0 {
		currComment.CommentContent = commentAndContent.comment.CommentContent
		currComment.Created = commentAndContent.comment.Created
		// 查询评论回复内容爬楼
		if commentAndContent.parentCommentId > 0 {
			parentComment := &rpc.CommentResult{
				CommentId: commentAndContent.parentCommentId,
			}
			parentRes, _, parentIsOk := c.recursionGetCommon(ctx, parentComment, depth, order+1)
			if parentIsOk {
				currComment.ParentComment = parentRes
			}
		}
		return currComment, contentInfo, true
	}
	return currComment, contentInfo, false
}

type commentInfo struct {
	comment         *rpc.CommentResult
	parentCommentId int64
	content         *rpc.CommentSourceContent
}

func (c *CommentServiceImpl) getCommentAndContent(ctx context.Context, currComment *rpc.CommentResult, isGetContent bool) (*commentInfo, bool) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "rpc.getCommentAndContent",
	})

	res := &commentInfo{
		comment: &rpc.CommentResult{
			CommentId: currComment.CommentId,
		},
	}
	var rpcRes *comment_thrift.CommentItem
	runFunc := func(ctx context.Context) error {
		commentRes, err := c.client.GetComment(ctx, currComment.CommentId, 0)
		if err != nil {
			logger.Errorf(ctx, "rpc comment:%+v error: %v", currComment, err)
			return err
		}
		rpcRes = commentRes
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	// 处理数据
	if rpcRes != nil && rpcRes.GetID() > 0 && !rpcRes.GetDeleted() {
		htmlText, htmlErr := util.ContentFilterHtml(ctx, rpcRes.GetContent())
		if htmlErr != nil {
			logger.Warnf(ctx, "comment:%d filter html error: %v", rpcRes.GetID(), htmlErr)
			return res, false
		}
		res.comment.CommentContent = htmlText
		res.comment.Created = rpcRes.GetCreated()
		res.comment.RootCommentId = rpcRes.GetReplyRoot()
		// 查询评论回复内容ID
		if rpcRes.GetReply() > 0 {
			res.parentCommentId = rpcRes.GetReply()
		}

		// 获取 content info
		docType := c.convert2ContentType(rpcRes.GetType())
		if isGetContent && docType != content.DocType_Unknown && rpcRes.GetObjectID() > 0 {
			modelContent := model.NewContentWithDocType(rpcRes.GetObjectID(), docType)
			contentInfoMap := c.contentClient.BatchGetContent(ctx, []model.Content{modelContent},
				base.ContentInfoFieldContentTitle,
				base.ContentInfoFieldContentDetail,
				base.ContentInfoFieldContentExtInfo,
				base.ContentInfoFieldContentBody)
			contentInfo, contentInfoIsOk := contentInfoMap[modelContent]
			if contentInfoIsOk && contentInfo.GetOutID() != "" && contentInfo.GetContentBody() != nil {
				commentSourceContent := &rpc.CommentSourceContent{
					PublishedTime: contentInfo.Published,
					ContentInfo:   contentInfo,
					DocId:         modelContent.ContentID,
					DocType:       modelContent.GetDocType(),
					ContentType:   modelContent.GetContentType(),
					Title:         contentInfo.GetTitle(),
				}
				body := contentInfo.GetContentBody().GetBody()
				filteredBody, err := util.ContentHtml2Markdown(ctx, body)
				if err == nil {
					commentSourceContent.Content = filteredBody
				}

				// 如果是Answer 再去取Question的title
				if docType == content.DocType_Answer {
					if contentInfo.GetExtInfo() != nil && contentInfo.GetExtInfo().GetParentInfo() != nil &&
						contentInfo.GetExtInfo().GetParentInfo().ContentID != "" {
						parentContentId := contentInfo.GetExtInfo().GetParentInfo().ContentID
						parentContentResultMap := c.contentClient.BatchGetContentByContentID(ctx, []string{parentContentId}, base.ContentInfoFieldContentTitle)
						parentContentInfo, parentContentInfoIsOk := parentContentResultMap[parentContentId]
						if parentContentInfoIsOk && parentContentInfo.GetOutID() != "" && parentContentInfo.GetTitle() != "" {
							commentSourceContent.Title = parentContentInfo.GetTitle()
						}
					}
				}

				res.content = commentSourceContent
			}
		}
	}
	return res, true
}

func (c *CommentServiceImpl) convert2ContentType(commentType comment_thrift.CommentType) content.DocType_Type {
	switch commentType {
	case comment_thrift.CommentType_ANSWER:
		return content.DocType_Answer
	case comment_thrift.CommentType_ARTICLE, comment_thrift.CommentType_ROUNDTABLE, comment_thrift.CommentType_ARTICLE_REVIEW, comment_thrift.CommentType_PROMOTION, comment_thrift.CommentType_EBOOK:
		return content.DocType_Article
	case comment_thrift.CommentType_QUESTION:
		return content.DocType_Question
	default:
		return content.DocType_Unknown
	}
}
