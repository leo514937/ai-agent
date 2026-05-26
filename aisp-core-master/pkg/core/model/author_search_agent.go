package model

import (
	"strings"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// 创作者 meta 信息，包括 raw 反序列化的结果和加工结果
type AuthorUserMeta struct {
	RecallIndexId     string  `json:"recall_index_id"`
	Headline          string  `json:"headline"`
	ArticleCnt        int     `json:"articleCnt"`
	AnswerCnt         int     `json:"answerCnt"`
	FollowerCnt       int     `json:"followerCnt"`
	FollowingCnt      int     `json:"followingCnt"`
	UpvoteCnt         int     `json:"upvoteCnt"`
	CollectionCnt     int     `json:"collectionCnt"`
	Boost             float64 `json:"boost"`
	AuthorId          string  `json:"authorId"`
	StaticDesc        string  `json:"static_author_desc"`
	RecentTopkDocsStr string  `json:"recent_topk_docs"`
	RecentTopkDocs    []Content
	Time              string `json:"time"`
	UpVoteTopkDocsStr string `json:"upvote_topk_docs"`
	UpVoteTopkDocs    []Content
	AuthorName        string `json:"authorName"`
	UrlToken          string `json:"url_token"`
	Url               string `json:"url"`
	Sentence          string `json:"sentence"`
	Description       string `json:"description"`
}

func RecentDocs2Contents(recentDocs string) []Content {
	contents := make([]Content, 0)
	if recentDocs == "" {
		return contents
	}
	docs := strings.Split(recentDocs, "\t")
	for _, doc := range docs {
		docContent := Content{}
		parts := strings.Split(doc, "-")
		if len(parts) != 2 {
			continue
		}
		contentId, err := util.String2Int64(parts[0])
		contentType := content.DocType_Type(content.DocType_Type_value[parts[1]])

		if err != nil || contentType == content.DocType_Unknown {
			continue
		}

		docContent.ContentID = contentId
		docContent.ContentType = contentType
		contents = append(contents, docContent)
	}
	return contents
}
