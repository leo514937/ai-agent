package rpc

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/thrift-go/zfav_go_thrift"
)

type ZFavRPC interface {
	// 获取用户获得的收藏数
	GetMemberRecievedCollection(ctx context.Context, memberId int64) int64
	ConcurrentGetMemberRecievedCollection(ctx context.Context, memberIds []int64, concurrency int) map[int64]int64

	// 获取用户的收藏夹列表
	ListMemberFavlist(ctx context.Context, memberId int64) []*zfav_go_thrift.Favlist
	// 获取收藏夹详情
	GetFavlist(ctx context.Context, memberId int64, favListId int64) *zfav_go_thrift.Favlist
	// 获取收藏夹下的内容列表
	ListFavlistItem(ctx context.Context, memberId int64, favListId int64) []*zfav_go_thrift.FavlistItem
}

var contentType2DocType = map[string]content.DocType_Type{
	"answer":  content.DocType_Answer,
	"article": content.DocType_Article,
}

func ContentType2DocType(contentType string) content.DocType_Type {
	if docType, ok := contentType2DocType[contentType]; ok {
		return docType
	}
	return content.DocType_Unknown
}
