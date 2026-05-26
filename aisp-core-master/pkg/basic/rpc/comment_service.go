package rpc

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

type CommentService interface {
	GetComment(ctx context.Context, commentId int64, depth int) (*CommentResultWrapper, bool)
}

type CommentSourceContent struct {
	PublishedTime int64                `json:"published_time"`
	ContentInfo   *base.ContentInfo    `json:"content_info"`
	DocId         int64                `json:"doc_id"`
	DocType       content.DocType_Type `json:"doc_type"`
	ContentType   string               `json:"content_type"`
	Title         string               `json:"title"`
	Content       string               `json:"content"`
}

type CommentResult struct {
	ParentComment  *CommentResult `json:"parent_comment"`
	RootCommentId  int64          `json:"root_comment_id"`
	CommentId      int64          `json:"comment_id"`
	CommentContent string         `json:"comment_content"`
	Created        int64          `json:"created"`
}

type CommentResultWrapper struct {
	Comment                  *CommentResult        `json:"comment"`
	CommentSourceContent     *CommentSourceContent `json:"comment_source_content"`
	RootComment              *CommentResult        `json:"root_comment"`
	RootCommentSourceContent *CommentSourceContent `json:"root_comment_source_content"`
}
