package author

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	util3 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

type AuthorDescService interface {
	BatchGetAuthorStatisticMeta(ctx context.Context, authorIds []int64) map[int64]*model.AuthorUserMeta
	BatchGetAuthorDetail(ctx context.Context, authorIds []int64) map[int64]*model.AuthorUserMeta
}

type AuthorDescServiceImpl struct {
	qaGoRPC          rpc.QaGoRPC
	articleRPC       rpc.ArticleRPC
	memberProfileRPC rpc.MemberProfileRPC
	contentCoreRpc   rpc.ContentCoreRPC
	contentProdRpc   rpc.ContentProdRPC
	zFavRPC          rpc.ZFavRPC
	memberRPC        rpc.MemberRPC
	rumClient        rpc.RumClient[float32]
	rumTable         string
}

var (
	DefaultAuthorDescService AuthorDescService
)

func init() {
	DefaultAuthorDescService = newAuthorDescService()
}

func newAuthorDescService() *AuthorDescServiceImpl {
	return &AuthorDescServiceImpl{
		qaGoRPC:          impl.DefaultQaGoRPCImpl,
		articleRPC:       impl.DefaultArticleRPCImpl,
		memberProfileRPC: impl.DefaultMemberProfileRPCImpl,
		contentCoreRpc:   impl.DefaultContentCoreRPCImpl,
		contentProdRpc:   impl.NewContentProdRPCImpl(),
		zFavRPC:          impl.DefaultZFavRPCImpl,
		memberRPC:        impl.DefaultMemberRPCImpl,
		rumClient:        impl.DefaultFloat32RumClientImpl,
		rumTable:         macro.ZhidaAuthorBgeRumTable,
	}
}

func (a *AuthorDescServiceImpl) BatchGetAuthorStatisticMeta(ctx context.Context, authorIds []int64) map[int64]*model.AuthorUserMeta {
	indexKeys := util3.BatchGetRumForwardKey(authorIds)
	rumSearchResult := a.rumClient.RumGet(ctx, a.rumTable, indexKeys, macro.ZhidaAuthorFields)
	resultMap := make(map[int64]*model.AuthorUserMeta)
	realtimeStatisticMap := a.getRealTimeStatistic(ctx, authorIds)

	for idx, searchItem := range rumSearchResult {
		fields := searchItem.(map[string]any)

		// 取出 rum 表中数据
		authorId := util.InterfaceTryGetInt64(fields[macro.ZhidaAuthorFiledNameAuthorId], 0)
		raw := util.InterfaceTryGetString(fields[macro.ZhidaAuthorFiledNameRaw], "")

		// 1、答主静态描述
		userMeta := &model.AuthorUserMeta{}
		_ = json.Unmarshal([]byte(raw), userMeta)
		userMeta.RecallIndexId = idx
		userMeta.RecentTopkDocs = model.RecentDocs2Contents(userMeta.RecentTopkDocsStr)
		userMeta.UpVoteTopkDocs = model.RecentDocs2Contents(userMeta.UpVoteTopkDocsStr)

		userMeta.Description = userMeta.StaticDesc
		userMeta.AnswerCnt = realtimeStatisticMap[authorId].AnswerCnt
		userMeta.ArticleCnt = realtimeStatisticMap[authorId].ArticleCnt
		userMeta.UpvoteCnt = realtimeStatisticMap[authorId].UpvoteCnt
		userMeta.CollectionCnt = realtimeStatisticMap[authorId].CollectionCnt
		userMeta.FollowingCnt = realtimeStatisticMap[authorId].FollowingCnt
		userMeta.FollowerCnt = realtimeStatisticMap[authorId].FollowerCnt
		resultMap[authorId] = userMeta
	}

	return resultMap
}

func (a *AuthorDescServiceImpl) BatchGetAuthorDetail(ctx context.Context, authorIds []int64) map[int64]*model.AuthorUserMeta {
	indexKeys := util3.BatchGetRumForwardKey(authorIds)
	rumSearchResult := a.rumClient.RumGet(ctx, a.rumTable, indexKeys, macro.ZhidaAuthorFields)

	resultMap := make(map[int64]*model.AuthorUserMeta)

	realtimeStatisticMap := a.getRealTimeStatistic(ctx, authorIds)

	currentTime := time.Now().Format("2006-01-02")
	for idx, searchItem := range rumSearchResult {
		fields := searchItem.(map[string]any)

		// 取出 rum 表中数据
		authorId := util.InterfaceTryGetInt64(fields[macro.ZhidaAuthorFiledNameAuthorId], 0)
		raw := util.InterfaceTryGetString(fields[macro.ZhidaAuthorFiledNameRaw], "")

		// 1、答主静态描述
		userMeta := &model.AuthorUserMeta{}
		_ = json.Unmarshal([]byte(raw), userMeta)
		userMeta.RecallIndexId = idx
		userMeta.RecentTopkDocs = model.RecentDocs2Contents(userMeta.RecentTopkDocsStr)
		userMeta.UpVoteTopkDocs = model.RecentDocs2Contents(userMeta.UpVoteTopkDocsStr)

		// 2、答主统计数据
		var authorStatisticText string
		publishText, interactionText := a.generateAuthorText(realtimeStatisticMap[authorId], userMeta.AuthorName)
		if publishText != "" || interactionText != "" {
			authorStatisticText = fmt.Sprintf("截止到%s，答主 %s 在知乎社区的贡献如下：\n%s\n%s", currentTime, userMeta.AuthorName, publishText, interactionText)
		}

		// 3、答主的个人主页
		userMeta.Url = fmt.Sprintf("https://www.zhihu.com/people/%s", userMeta.UrlToken)
		homePageText := fmt.Sprintf("更多关于答主 %s 的信息可以去[知乎答主 %s 的个人主页](%s)查看。", userMeta.AuthorName, userMeta.AuthorName, userMeta.Url)

		// 4、答主创作内容
		var upVoteTopkText, recentTopkText string
		if len(userMeta.UpVoteTopkDocs) > 0 {
			upVoteTopkText = fmt.Sprintf("答主 %s 创作的前 %d 个高赞内容如下：\n%s",
				userMeta.AuthorName,
				utils.MinInt(len(userMeta.UpVoteTopkDocs), 20),
				a.getDocDescriptions(a.getDocMetas(ctx, userMeta.UpVoteTopkDocs), 20),
			)
		}
		if len(userMeta.RecentTopkDocs) > 0 {
			recentTopkText = fmt.Sprintf("答主 %s 最近创作的 %d 个内容如下：\n%s",
				userMeta.AuthorName,
				utils.MinInt(len(userMeta.RecentTopkDocs), 20),
				a.getDocDescriptions(a.getDocMetas(ctx, userMeta.RecentTopkDocs), 20),
			)
		}

		// 将上述四点按顺序拼接
		authorDesc := fmtEmptyLine(fmt.Sprintf("%s\n%s\n%s\n\n%s\n\n%s",
			userMeta.StaticDesc,
			authorStatisticText,
			homePageText,
			upVoteTopkText,
			recentTopkText,
		))
		userMeta.Description = authorDesc

		userMeta.AnswerCnt = realtimeStatisticMap[authorId].AnswerCnt
		userMeta.ArticleCnt = realtimeStatisticMap[authorId].ArticleCnt
		userMeta.UpvoteCnt = realtimeStatisticMap[authorId].UpvoteCnt
		userMeta.CollectionCnt = realtimeStatisticMap[authorId].CollectionCnt
		userMeta.FollowingCnt = realtimeStatisticMap[authorId].FollowingCnt
		userMeta.FollowerCnt = realtimeStatisticMap[authorId].FollowerCnt

		resultMap[authorId] = userMeta
	}

	return resultMap
}

func (a *AuthorDescServiceImpl) getRealTimeStatistic(ctx context.Context, memberIds []int64) map[int64]*model.AuthorUserMeta {
	var answerMap = make(map[int64]int64)
	var articleMap = make(map[int64]int64)
	var voteupMap = make(map[int64]int64)
	var collectionMap = make(map[int64]int64)
	var followingMap = make(map[int64]int64)
	var followerMap = make(map[int64]int64)

	var resultMap = make(map[int64]*model.AuthorUserMeta)
	sg := safe_group.NewGroup("BatchGetCounter")
	sg.Go(func() error {
		answerMap = a.qaGoRPC.BatchGetMemberCreateAnswerCount(ctx, memberIds)
		return nil
	})
	sg.Go(func() error {
		articleMap = a.articleRPC.BatchGetMemberCreateArticleCount(ctx, memberIds)
		return nil
	})
	sg.Go(func() error {
		voteupMap = a.memberProfileRPC.BatchGetMemberRecievedVoteup(ctx, memberIds)
		return nil
	})
	sg.Go(func() error {
		collectionMap = a.zFavRPC.ConcurrentGetMemberRecievedCollection(ctx, memberIds, 5)
		return nil
	})
	sg.Go(func() error {
		followingMap = a.memberRPC.BatchGetMemberFollowingCount(ctx, memberIds)
		return nil
	})
	sg.Go(func() error {
		followerMap = a.memberRPC.BatchGetMemberFollowerCount(ctx, memberIds)
		return nil
	})
	err := sg.Wait()
	if err != nil {
		log.Errorf(ctx, "get member statistic safe_group wait error => %v", err)
	}

	for _, authorId := range memberIds {
		authorUserMeta := &model.AuthorUserMeta{
			AnswerCnt:     int(answerMap[authorId]),
			ArticleCnt:    int(articleMap[authorId]),
			UpvoteCnt:     int(voteupMap[authorId]),
			CollectionCnt: int(collectionMap[authorId]),
			FollowingCnt:  int(followingMap[authorId]),
			FollowerCnt:   int(followerMap[authorId]),
		}
		resultMap[authorId] = authorUserMeta
	}

	return resultMap
}

func (a *AuthorDescServiceImpl) generateAuthorText(authorUserMeta *model.AuthorUserMeta, authorName string) (string, string) {
	var publishText, interactionText string

	var answerText, articleText string
	if authorUserMeta.AnswerCnt > 0 {
		answerText = fmt.Sprintf("回答了 %d 个问题", authorUserMeta.AnswerCnt)
	}
	if authorUserMeta.ArticleCnt > 0 {
		articleText = fmt.Sprintf("发布了 %d 篇专业文章", authorUserMeta.ArticleCnt)
	}
	if answerText != "" || articleText != "" {
		publishText = fmt.Sprintf("答主 %s 在知乎社区共%s。", authorName, wordJoin([]string{answerText, articleText}, "，"))
	}

	var upvoteText, collectionText, actionText, followerText string
	if authorUserMeta.UpvoteCnt > 0 {
		upvoteText = fmt.Sprintf("%d 次赞同", authorUserMeta.UpvoteCnt)
	}
	if authorUserMeta.CollectionCnt > 0 {
		collectionText = fmt.Sprintf("%d 次收藏", authorUserMeta.CollectionCnt)
	}
	if authorUserMeta.FollowerCnt > 0 {
		followerText = fmt.Sprintf("吸引了 %d 名粉丝的关注", authorUserMeta.FollowerCnt)
	}
	if upvoteText != "" || collectionText != "" {
		actionText = fmt.Sprintf("获得了 %s", wordJoin([]string{upvoteText, collectionText}, "和 "))
	}
	if actionText != "" || followerText != "" {
		interactionText = fmt.Sprintf("答主 %s 已累积%s。", authorName, wordJoin([]string{actionText, followerText}, "，"))
	}

	return publishText, interactionText
}

type DocMeta struct {
	upvoteCnt   int64
	publishTime string
	title       string
	url         string
	docType     string
}

func (a *AuthorDescServiceImpl) getDocMetas(ctx context.Context, docs []model.Content) []*DocMeta {
	// 自身 meta 信息
	contentMetaMap := a.contentCoreRpc.BatchGetContent(ctx, docs,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentExtInfo,
	)

	// parent meta 信息
	var parentContentIds []string
	for _, contentInfo := range contentMetaMap {
		if contentInfo.GetExtInfo() != nil && contentInfo.GetExtInfo().GetParentInfo() != nil &&
			contentInfo.GetExtInfo().GetParentInfo().ContentID != "" {
			parentContentIds = append(parentContentIds, contentInfo.GetExtInfo().GetParentInfo().ContentID)
		}
	}
	parentContentMetaMap := a.contentCoreRpc.BatchGetContentByContentID(ctx, parentContentIds, base.ContentInfoFieldContentTitle)

	// 自身统计信息
	contentStatisticMap := a.contentProdRpc.BatchGetContent(ctx, docs, &content.WithFieds{
		StatisticsFields: &content.StatisticsFields{
			AllStatistics: lo.ToPtr(true),
		},
	})

	// 组装最终结果
	var result []*DocMeta
	for _, doc := range docs {
		contentInfo, isOk := contentMetaMap[doc]
		if !isOk {
			continue
		}
		title := contentInfo.GetTitle()
		if title == "" && contentInfo.GetExtInfo() != nil && contentInfo.GetExtInfo().GetParentInfo() != nil &&
			contentInfo.GetExtInfo().GetParentInfo().ContentID != "" && parentContentMetaMap[contentInfo.GetExtInfo().GetParentInfo().ContentID] != nil {
			title = parentContentMetaMap[contentInfo.GetExtInfo().GetParentInfo().ContentID].GetTitle()
		}

		var url string
		if contentInfo.GetExtInfo() != nil {
			url = contentInfo.GetExtInfo().GetURL()
		}

		var upvoteCnt int64
		if contentStatisticMap[doc] != nil && contentStatisticMap[doc].GetContentStatistics() != nil {
			upvoteCnt = contentStatisticMap[doc].GetContentStatistics().GetUpVoteCount()
		}

		publishTime := time.Unix(contentInfo.GetPublished(), 0).Format("2006-01-02")

		result = append(result, &DocMeta{
			upvoteCnt:   upvoteCnt,
			publishTime: publishTime,
			title:       title,
			url:         url,
			docType:     getDocType(doc.GetDocType()),
		})
	}

	return result
}

func getDocType(docType content2.DocType_Type) string {
	switch docType {
	case content2.DocType_Article:
		return "知乎文章"
	case content2.DocType_Answer:
		return "知乎回答"
	case content2.DocType_ZVideo:
		return "知乎视频"
	case content2.DocType_Pin:
		return "知乎想法"
	default:
		return "知乎内容"
	}
}

func (a *AuthorDescServiceImpl) getDocDescriptions(docs []*DocMeta, limit int) string {
	var result []string
	for idx, doc := range docs {
		if idx >= limit {
			break
		}
		result = append(result, fmt.Sprintf("<知乎内容 类型=\"%s\" 点赞数=%d  发布时间=\"%s\">[%s](%s)</知乎内容>",
			doc.docType, doc.upvoteCnt, doc.publishTime, doc.title, doc.url))
	}
	return strings.Join(result, "\n")
}

func wordJoin(words []string, sep string) string {
	var validWords []string
	for _, word := range words {
		if word != "" {
			validWords = append(validWords, word)
		}
	}
	return strings.Join(validWords, sep)
}

// 连续多个空行替换为一个空行
func fmtEmptyLine(input string) string {
	re := regexp.MustCompile(`\n{3,}`)
	return re.ReplaceAllString(input, "\n\n")
}
