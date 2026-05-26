package entities

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_biz_ext/paper_biz_ext"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/cespare/xxhash/v2"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type Item struct {
	MessageId            string                // 消息唯一ID
	TimestampMs          int64                 // 消息毫秒时间戳
	ChatTextTurnoverType ChatMappingType       // 对话文本流转类型
	Type                 proto.ChatMessageType // 消息类型
	Text                 string                // 文本消息/Query
	Think                string                // 思考过程
	QueryType            proto.QueryType       // 词业务类型
	QueryId              string                // 词ID
	QueryScore           float64               // 词Score
	QueryCensorType      string                // 负反馈类型
	ChatRespType         proto.ChatRespType    // 回答类型
	ExtraInfo            *proto.ExtraRespInfo  // 业务额外信息
	ItemMeta             *model.ItemMeta       // 当前 item 的 meta 信息
	Security             *model.Security       // 当前 item 的安审结果
	IsVisible            bool                  // 是否展示
	IsCitable            bool                  // 是否可引用
	OrderNumber          int                   // 序号
	Snippets             []*Snippet            // 分句数据
	CiteMaxScore         float64               // 最大分数
	PageItems            []*Item               // 分页数据
	ViewKbCount          int                   // 阅读参考文献数
	// 算子维度内容信息
	frameItem *data_frame.ItemData[Item]
}

func (i *Item) GetPageItems(ctx context.Context) []*Item {
	if i.PageItems != nil {
		return i.PageItems
	}

	pageItems := make([]*Item, 0)

	if i.GetItemMeta().DocumentParsing == nil {
		return pageItems
	}
	documentParsing := i.ItemMeta.DocumentParsing

	log.Infof(ctx, "GetPageItems documentParsing: %s", util.GetJSONIgnoreError(documentParsing))

	allText := []rune(documentParsing.Text)

	lastPage := 0
	lbound := 0
	rbound := 0

	for i, page := range documentParsing.Pages {
		if i >= len(documentParsing.Rbounds) {
			break
		}

		pageNumber := int(page)
		if pageNumber == lastPage {
			rbound = int(documentParsing.Rbounds[i])

			continue
		}

		pageText := allText[lbound:rbound]
		pageItem := ItemWithTextAndType(string(pageText), ChatMappingTypePage)
		pageItem.OrderNumber = lastPage
		pageItems = append(pageItems, pageItem)

		lastPage = pageNumber
		lbound = rbound
		rbound = int(documentParsing.Rbounds[i])
	}

	// 处理最后一页
	pageText := allText[lbound:rbound]
	pageItem := ItemWithTextAndType(string(pageText), ChatMappingTypePage)
	pageItem.OrderNumber = lastPage
	pageItems = append(pageItems, pageItem)

	log.Infof(ctx, "GetPageItems pageItems: %s", util.GetJSONIgnoreError(pageItems))

	i.PageItems = pageItems
	return pageItems
}

type Snippet struct {
	Content        string    // 段落内容
	Embedding      []float32 // 嵌入信息
	CharMatchScore float64   // 字符匹配得分
	CosineScore    float64   // 余弦相似度得分
	Score          float64   // 段落得分
	Item           *Item     // 当前 item
}

type CiteSnippet struct {
	DocIndex    int               // 参考来源里 doc 的索引
	CiteId      int               // 角标 id
	DocSentence string            // 文章中的句子
	DocAbstract string            // 摘要
	Embedding   []float32         // 句子的嵌入信息
	Score       float64           // 角标得分
	Rank        int               // 排序, 0 普通, 1 c4+答主, 2 白名单答主
	CiteBizType proto.CiteBizType // 角标业务类型
}

func (c *CiteSnippet) CopyCite() *CiteSnippet {
	return &CiteSnippet{
		DocIndex:    c.DocIndex,
		CiteId:      c.CiteId,
		DocSentence: c.DocSentence,
		DocAbstract: c.DocAbstract,
		Embedding:   c.Embedding,
		Score:       c.Score,
		Rank:        c.Rank,
		CiteBizType: c.CiteBizType,
	}
}

func (c *CiteSnippet) ToEventCite() *chat_event.CiteSnippetDto {
	return &chat_event.CiteSnippetDto{
		DocIndex:    c.DocIndex,
		CiteId:      c.CiteId,
		DocSentence: c.DocSentence,
		DocAbstract: c.DocAbstract,
		Score:       c.Score,
		CiteBizType: c.CiteBizType,
	}
}

func (i *Item) GetSecurity() *model.Security {
	if i.Security == nil {
		i.Security = &model.Security{
			ReviewResult: &model.ReviewResult{
				IsAvailable: true,
			},
		}
	}
	return i.Security
}

func (i *Item) GetItemMeta() *model.ItemMeta {
	if i.ItemMeta == nil {
		i.ItemMeta = &model.ItemMeta{}
	}

	return i.ItemMeta
}

type ChatMappingType int64

func (r ChatMappingType) ToConvert() int64 {
	return int64(r)
}

func (r ChatMappingType) ToConvertStr() string {
	return cast.ToString(r.ToConvert())
}

const (
	// ChatMappingTypeUnknown 未知
	ChatMappingTypeUnknown ChatMappingType = 0
	// ChatMappingTypeQuery Query 请求
	ChatMappingTypeQuery ChatMappingType = 1
	// ChatMappingTypeQueryMerge QueryMerge 请求
	ChatMappingTypeQueryMerge ChatMappingType = 2
	// ChatMappingTypeRecallDoc 索引召回
	ChatMappingTypeRecallDoc ChatMappingType = 3
	// ChatMappingTypeRecallChunk 索引召回段落
	ChatMappingTypeRecallChunk ChatMappingType = 4
	// ChatMappingTypePage 分页数据
	ChatMappingTypePage ChatMappingType = 4
	// ChatMappingTypeQueryPrompt query prompt
	ChatMappingTypeQueryPrompt ChatMappingType = 5
	// ChatMappingTypeSystemPrompt system prompt
	ChatMappingTypeSystemPrompt ChatMappingType = 6
	// ChatMappingTypeLLMAnswer 大模型回答结果
	ChatMappingTypeLLMAnswer ChatMappingType = 7
	// ChatMappingTypeSummary 生成 summary
	ChatMappingTypeSummary ChatMappingType = 8
	// ChatMappingTypeQuestion 生成 问题
	ChatMappingTypeQuestion ChatMappingType = 9
	// ChatMappingTypeEndEmpty 空类型结束节点
	ChatMappingTypeEndEmpty ChatMappingType = 10
)

func NewItem(frameItem *data_frame.ItemData[Item]) *Item {
	return &Item{
		frameItem: frameItem,
	}
}
func ItemFromEndEmpty() *Item {
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeEndEmpty,
	}
	item.initItem()
	return item
}
func ItemFromQueryMerge(m *Item, text string) *Item {
	if text == "" {
		text = m.Text
	}
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeQueryMerge,
		MessageId:            m.MessageId,
		TimestampMs:          m.TimestampMs,
		Type:                 m.Type,
		Text:                 text,
	}
	item.initItem()
	return item
}
func ItemFromSummary(summaryRes string, orderGroup int) *Item {
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 summaryRes,
		ItemMeta: &model.ItemMeta{
			RecallSourceInfo: &model.RecallSourceInfo{
				OrderGroup: orderGroup,
			},
		},
	}
	item.initItem()
	return item
}

func ItemFromSummaryOtherRecall(title string, snippet string, url string, mainText string, kbSource conf.KbSource, orderGroup int) *Item {
	if mainText == "" {
		mainText = snippet
	}
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 mainText,
		ItemMeta: &model.ItemMeta{
			Title:         title,
			Url:           url,
			DocType:       content.DocType_Link,
			Abstract:      util.UnicodeSubstr(snippet, 0, macro.CardAbstractLimit),
			OriginSnippet: snippet,
			Content:       mainText,
			RecallSourceInfo: &model.RecallSourceInfo{
				OrderGroup: orderGroup,
				KbSources:  []conf.KbSource{kbSource},
			},
		},
	}
	item.initItem()
	return item
}

func ItemFromSecurityFailed(refuseText string, messageId string) *Item {
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeLLMAnswer,
		MessageId:            messageId,
		TimestampMs:          time.Now().UnixMilli(),
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 refuseText,
		ChatRespType:         proto.ChatRespType_REFUSE,
	}
	item.initItem()
	return item
}

func ItemFromMessage(m *proto.ChatMessage) *Item {
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeQuery,
		MessageId:            m.MessageId,
		TimestampMs:          m.TimestampMs,
		Type:                 m.Type,
		Text:                 m.Text,
	}
	item.initItem()
	return item
}

func ItemFromMessageByAnswer(m *proto.ChatMessage) *Item {
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeLLMAnswer,
		MessageId:            m.MessageId,
		TimestampMs:          m.TimestampMs,
		Type:                 m.Type,
		Text:                 m.Text,
	}
	item.initItem()
	return item
}

func ItemFromMessageByAnswerAndType(m *proto.ChatMessage, respType proto.ChatRespType) *Item {
	item := &Item{
		ChatTextTurnoverType: ChatMappingTypeLLMAnswer,
		MessageId:            m.MessageId,
		TimestampMs:          m.TimestampMs,
		Type:                 m.Type,
		Text:                 m.Text,
		ChatRespType:         respType,
	}
	item.initItem()
	return item
}

func ItemFromQuery(q *proto.Query, queryScore float64, censorType string) *Item {
	item := &Item{
		MessageId:       "",
		TimestampMs:     0,
		Type:            proto.ChatMessageType_TEXT,
		Text:            q.Query,
		QueryType:       q.QueryType,
		QueryId:         q.Id,
		QueryScore:      queryScore,
		QueryCensorType: censorType,
	}
	item.initItem()
	return item
}

func ItemWithTextAndType(text string, chatTextTurnoverType ChatMappingType) *Item {
	item := &Item{
		MessageId:            "",
		TimestampMs:          0,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 text,
		ChatTextTurnoverType: chatTextTurnoverType,
	}
	item.initItem()
	return item
}

func ItemFromMessageAndType(m *proto.ChatMessage, chatTextTurnoverType ChatMappingType) *Item {
	item := &Item{
		ChatTextTurnoverType: chatTextTurnoverType,
		MessageId:            m.MessageId,
		TimestampMs:          m.TimestampMs,
		Type:                 m.Type,
		Text:                 m.Text,
	}
	item.initItem()
	return item
}

func ItemFromDialogueRecord(dialogue *model.DialogRecord) *Item {
	var chatTextTurnoverType ChatMappingType
	if dialogue.RoleType == model.RoleTypeUser.ToConvert() {
		chatTextTurnoverType = ChatMappingTypeQuery
	} else {
		chatTextTurnoverType = ChatMappingTypeLLMAnswer
	}
	item := &Item{
		MessageId:            dialogue.MessageId,
		TimestampMs:          dialogue.RecordAt.UnixMilli(),
		ChatTextTurnoverType: chatTextTurnoverType,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 dialogue.MessageContent,
	}
	item.initItem()
	return item
}

// 有一些字段不想后面每次都判断空指针，进行初始化
func (i *Item) initItem() {
	if i.Security == nil {
		i.Security = &model.Security{
			ReviewResult: &model.ReviewResult{
				IsAvailable: true,
			},
		}
	}
	if i.ItemMeta == nil {
		i.ItemMeta = &model.ItemMeta{
			PrefixCache: sync.Map{},
		}
	}
}

func (i *Item) ToChatMessage() *proto.ChatMessage {
	return &proto.ChatMessage{
		MessageId:   i.MessageId,
		TimestampMs: i.TimestampMs,
		Type:        i.Type,
		Text:        i.Text,
	}
}

// ToChatCard 转换为卡片 (旧版 现已废弃)
func (i *Item) ToChatCard() *proto.ChatCard {
	var card *proto.ChatCard = nil
	// 只返回允许发送的卡片
	if i.GetItemMeta().IsNotAllowSend {
		return card
	}
	if i.GetItemMeta().IsOutLink() || i.GetItemMeta().DocType == content.DocType_Link {
		// 非法判断
		if i.GetItemMeta().Title != "" && i.GetItemMeta().Url != "" {
			card = &proto.ChatCard{
				CardContent: &proto.ChatCard_OtherRelevantSource{
					OtherRelevantSource: &proto.ChatCardOtherRelevantSource{
						DocTitle:        i.GetItemMeta().Title,
						DocUrl:          i.GetItemMeta().Url,
						DocAbstract:     i.GetItemMeta().Abstract,
						RecallContentId: i.GetItemRecallContentId(),
					},
				},
			}
		}
	} else if i.GetItemMeta().DocType == content.DocType_Member {
		card = &proto.ChatCard{
			CardContent: &proto.ChatCard_ZhihuRelevantSource{
				ZhihuRelevantSource: &proto.ChatCardZhihuRelevantSource{
					DocId:           i.GetItemMeta().AuthorId,
					DocType:         i.GetItemMeta().GetCardDocType(),
					RecallContentId: i.GetItemRecallContentId(),
				},
			},
		}
	} else {
		card = &proto.ChatCard{
			CardContent: &proto.ChatCard_ZhihuRelevantSource{
				ZhihuRelevantSource: &proto.ChatCardZhihuRelevantSource{
					DocId:           i.GetItemMeta().DocId,
					DocType:         i.GetItemMeta().GetCardDocType(),
					RecallContentId: i.GetItemRecallContentId(),
				},
			},
		}
	}

	return card
}

func (i *Item) ToRecallItem() *proto.ZhidaRecallItem {
	// 只有站外内容塞摘要和正文，其余直接从内容平台获取
	var abstract, docContent string
	if i.GetItemMeta().IsOutLink() {
		abstract = i.GetItemMeta().Abstract
		docContent = i.GetItemMeta().Content
	}
	return &proto.ZhidaRecallItem{
		DocId:             i.GetItemMeta().DocId,
		DocType:           util.DocType2ContentType(i.GetItemMeta().DocType),
		Title:             i.GetItemMeta().GetTitle(),
		Abstract:          abstract,
		Content:           docContent,
		Url:               i.GetItemMeta().Url,
		RecallSource:      i.GetItemMeta().GetRecallSourceInfo().GetFirstKbSource().String(),
		RecallScore:       i.GetItemMeta().GetRecallSourceInfo().RecallScore,
		KnowledgeBaseId:   i.GetItemMeta().GetRecallSourceInfo().KnowledgeBaseId,
		KnowledgeBaseType: i.GetItemMeta().GetRecallSourceInfo().PersonalKnowledgeBaseType,
	}
}

// proto.ZhidaRecallItem 转 item
func RecallItem2Item(input *proto.ZhidaRecallItem) *Item {
	item := &Item{
		MessageId:   "",
		TimestampMs: 0,
		Type:        proto.ChatMessageType_TEXT,
		ItemMeta: &model.ItemMeta{
			DocId:    input.DocId,
			DocType:  util.ContentType2DocType(input.DocType),
			Title:    input.Title,
			Url:      input.Url,
			Abstract: input.Abstract,
			Content:  input.Content,
			RecallSourceInfo: &model.RecallSourceInfo{
				KbSources:                 []conf.KbSource{conf.KbSource(input.RecallSource)},
				RecallScore:               input.RecallScore,
				KnowledgeBaseId:           input.KnowledgeBaseId,
				PersonalKnowledgeBaseType: input.KnowledgeBaseType,
			},
		},
	}
	item.initItem()
	return item
}

// ToChatCardByZhiDa 转换为卡片 (新版 拍平返回类型为同一个类)
func (i *Item) ToChatCardByZhiDa() *proto.ChatCard {
	var card *proto.ChatCard = nil
	// 只返回允许发送的卡片
	if i.GetItemMeta().IsNotAllowSend {
		return card
	}
	if i.GetItemMeta().DocType == content.DocType_Link {
		// 非法判断
		if i.GetItemMeta().Title != "" && i.GetItemMeta().Url != "" {
			card = &proto.ChatCard{
				CardContent: &proto.ChatCard_ZhidaRelevantSource{
					ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
						DocId:       i.GetItemMeta().Url,
						DocType:     proto.DocType_UNIVERSAL_OFFSITE,
						DocTitle:    i.GetItemMeta().Title,
						DocAbstract: i.GetItemMeta().Abstract,
					},
				},
			}
		}
	} else if i.GetItemMeta().DocType == content.DocType_Member {
		card = &proto.ChatCard{
			CardContent: &proto.ChatCard_ZhidaRelevantSource{
				ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
					DocId:   cast.ToString(i.GetItemMeta().AuthorId),
					DocType: proto.DocType_MEMBER,
				},
			},
		}
	} else if i.GetItemMeta().DocType == content.DocType_InternalDoc {
		card = &proto.ChatCard{
			CardContent: &proto.ChatCard_OtherRelevantSource{
				OtherRelevantSource: &proto.ChatCardOtherRelevantSource{
					DocTitle:        i.GetItemMeta().Title,
					DocUrl:          i.GetItemMeta().Url,
					RecallContentId: util.Int64String(i.GetItemMeta().DocId),
				},
			},
		}
	} else {
		// 知乎内容平台内容 包含 Answer Article Paper ZhidaUserUpload、AispUserUpload 等等。所有 meta 信息由内容平台出，此处不返回标题和摘要
		itemModel := model.NewContentWithDocType(i.GetItemMeta().DocId, i.GetItemMeta().DocType)
		docType := itemModel.GetZhiDaDocType()
		if docType != proto.DocType_UNKNOWN_DOCTYPE {
			card = &proto.ChatCard{
				CardContent: &proto.ChatCard_ZhidaRelevantSource{
					ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
						DocId:   cast.ToString(i.GetItemMeta().DocId),
						DocType: docType,
					},
				},
			}
		}
	}
	return card
}

// ToChatCardByMCP 转换为mcp卡片
func (i *Item) ToChatCardByMCP() *proto.ChatCard {
	var card *proto.ChatCard = nil
	// 只返回允许发送的卡片
	if i.GetItemMeta().IsNotAllowSend {
		return card
	}

	abstract := i.Text
	if util.UnicodeLen(abstract) > 200 { // 正文已 5k 字过安全
		abstract = util.UnicodeSubstr(abstract, 0, 200) + "..."
	}

	card = &proto.ChatCard{
		CardContent: &proto.ChatCard_ZhidaRelevantSource{
			ZhidaRelevantSource: &proto.ChatCardProRelevantSource{
				DocId:       i.GetItemMeta().Url,
				DocType:     proto.DocType_UNIVERSAL_OFFSITE,
				DocTitle:    i.GetItemMeta().Title,
				DocAbstract: abstract,
			},
		},
	}
	return card
}

func (i *Item) ToQuery() *proto.Query {
	return &proto.Query{
		QueryType: i.QueryType,
		Id:        i.QueryId,
		Query:     i.Text,
		RiskType:  i.QueryCensorType,
	}
}

func (i *Item) IntoFrameItem(requestCtx *data_frame.RequestContext[RequestContext, User, Item]) *data_frame.ItemData[Item] {
	// 如果已经有 frameItem，直接返回
	if i.frameItem != nil {
		return i.frameItem
	}

	frameItem := data_frame.NewItemData(requestCtx)
	i.SetFrameItem(frameItem)
	frameItem.SetBizItem(i)

	// hash生成唯一id
	docId := int64(xxhash.Sum64String(fmt.Sprintf("%s-%d-%d", i.Text, i.GetItemMeta().DocId, i.GetItemMeta().DocType)))

	frameItem.GetCommonItem().SetId(&content.DocIdentity{
		Id:      docId,
		DocType: content.DocType_Text,
	})
	return frameItem
}

func (i *Item) FrameItem() *data_frame.ItemData[Item] {
	return i.frameItem
}

func (i *Item) SetFrameItem(frameItem *data_frame.ItemData[Item]) {
	i.frameItem = frameItem
}

func (i *Item) ToString() string {
	return fmt.Sprintf("[%s]%s", i.MessageId, i.Text)
}

func (i *Item) ToDescription() string {
	title := i.GetItemMeta().Title
	if title == "" && i.GetItemMeta().ParentContentInfo != nil {
		title = i.GetItemMeta().ParentContentInfo.GetTitle()
	}
	docId := i.ItemMeta.DocId
	if i.ItemMeta.DocType == content.DocType_Member {
		docId = i.ItemMeta.AuthorId
	}
	return fmt.Sprintf("docId:%d,docType:%s,url:%s,title:%s,source:%s", docId, i.ItemMeta.DocType.String(),
		i.ItemMeta.Url, title, util.GetJSONIgnoreError(i.ItemMeta.RecallSourceInfo.KbSources))
}

// IsHitFilterWhiteList 是否命中于过滤白名单
func (i *Item) IsHitFilterWhiteList(filterIncludeDocTypeArr []content.DocType_Type, filterIncludePaperArr []paper_biz_ext.PaperPublishSource) bool {
	// 如果当前 不在 docType 白名单中 则直接跳过
	if !lo.Contains(filterIncludeDocTypeArr, i.GetItemMeta().DocType) {
		return false
	}
	// 如果指定了paper的白名单 还需要额外判断一下 当天item 是否在paper的白名单中
	if len(filterIncludePaperArr) > 0 &&
		i.GetItemMeta().DocType == content.DocType_Paper &&
		lo.Contains(filterIncludeDocTypeArr, i.GetItemMeta().DocType) {
		if i.GetItemMeta().ContentInfo != nil &&
			i.GetItemMeta().ContentInfo.GetBizExtDetail() != nil &&
			i.GetItemMeta().ContentInfo.GetBizExtDetail().GetPaperBizExt() != nil {
			if !lo.Contains(filterIncludePaperArr, i.GetItemMeta().ContentInfo.GetBizExtDetail().GetPaperBizExt().Source) {
				return false
			}
		} else {
			return false
		}
	}
	return true
}

// GetItemRecallContentId 获取召回内容ID
func (i *Item) GetItemRecallContentId() string {
	return GetRecallContentId(i.GetItemMeta().DocId, i.GetItemMeta().DocType, i.GetItemMeta().Url)
}
func GetRecallContentId(docId int64, docType content.DocType_Type, url string) string {
	return fmt.Sprintf("%v|:|%v|:|%s", docId, docType, url)
}

func LogUser(val *data_frame.UserData[User]) log.Field {
	inner := val.GetBizUser()

	user := fmt.Sprintf("member_id=%d", inner.MemberId)

	return log.String("user", user)
}

func LogMemberId(memberId int64) log.Field {
	user := fmt.Sprintf("member_id=%d", memberId)

	return log.String("user", user)
}

func fmtItem(item *Item) string {
	return fmt.Sprintf("type=%s text=%s", item.ChatTextTurnoverType.ToConvertStr(), log.Omit(item.Text))
}

func LogItem(val *data_frame.ItemData[Item]) log.Field {
	inner := val.GetBizItem()

	text := fmtItem(inner)

	return log.String("item", text)
}

func LogItems(val []*data_frame.ItemData[Item]) log.Field {
	items := make([]string, 0)
	for i, item := range val {
		inner := item.GetBizItem()
		text := "..."
		if i < 2 || i == len(val)-1 {
			text = fmtItem(inner)
		}
		items = append(items, text)
	}

	return log.String("items", strings.Join(items, "\t"))
}

func LogItemLists(val [][]*data_frame.ItemData[Item]) log.Field {
	innerLists := make([]string, 0)
	for _, itemList := range val {
		items := make([]string, 0)
		for i, item := range itemList {
			inner := item.GetBizItem()
			text := "..."
			if i < 2 || i == len(itemList)-1 {
				text = fmtItem(inner)
			}
			items = append(items, text)
		}

		texts := strings.Join(items, "\t")
		innerLists = append(innerLists, texts)
	}

	return log.String("item_lists", strings.Join(innerLists, "\n"))
}

func ItemListMergeDuplicate(itemList []*data_frame.ItemData[Item]) []*data_frame.ItemData[Item] {
	var result []*data_frame.ItemData[Item]

	onsiteDocIds := map[string]bool{}
	onsiteAuthorIds := map[int64]*data_frame.ItemData[Item]{}
	var urls []string

	itemTypeMap := lo.GroupBy(itemList, func(item *data_frame.ItemData[Item]) string {
		switch item.GetBizItem().GetItemMeta().DocType {
		case content.DocType_Answer, content.DocType_Article, content.DocType_Paper, content.DocType_ZhiDaUserUpload, content.DocType_Webpage, content.DocType_CrawlerWebpage:
			return "insite_doc"
		case content.DocType_Member:
			return "author"
		}
		return "outsite_doc"
	})

	// 先存放站内内容
	for _, item := range itemTypeMap["insite_doc"] {
		docId := item.GetBizItem().GetItemMeta().DocId
		docType := item.GetBizItem().GetItemMeta().DocType
		url := item.GetBizItem().GetItemMeta().Url
		uniqueKey := fmt.Sprintf("docId:%d-docType:%s", docId, docType)

		if !onsiteDocIds[uniqueKey] {
			result = append(result, item)
			onsiteDocIds[uniqueKey] = true
			if url != "" {
				urls = append(urls, url)
			}
		}
	}

	// 再存放创作者内容
	for _, item := range itemTypeMap["author"] {
		authorId := item.GetBizItem().GetItemMeta().AuthorId
		url := item.GetBizItem().GetItemMeta().Url
		if uniqueItem, exist := onsiteAuthorIds[authorId]; !exist {
			result = append(result, item)
			urls = append(urls, url)
			onsiteAuthorIds[authorId] = item
		} else {
			uniqueItem.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources = conf.KbSourceSort(lo.Uniq(append(
				uniqueItem.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources,
				item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources...,
			)))
		}
	}

	// 最后放站外召回源
	for _, item := range itemTypeMap["outsite_doc"] {
		url := item.GetBizItem().GetItemMeta().Url
		if !urlExist(urls, url) {
			result = append(result, item)
			urls = append(urls, url)
		}
	}

	return result
}

func urlExist(urls []string, url string) bool {
	if strings.Contains(url, "www.zhihu.com/question") ||
		strings.Contains(url, "www.zhihu.com/answer") ||
		strings.Contains(url, "zhuanlan.zhihu.com/p") ||
		strings.Contains(url, "www.zhihu.com/people") {
		for _, each := range urls {
			if strings.Contains(each, url) || strings.Contains(url, each) {
				return true
			}
		}
		return false
	} else {
		return lo.Contains(urls, url)
	}
}

// ItemListDeduplicateWithPriority 对两个列表进行去重，重复时保留第一个列表中的实例
func ItemListDeduplicateWithPriority(priorityList []*data_frame.ItemData[Item], secondaryList []*data_frame.ItemData[Item]) []*data_frame.ItemData[Item] {
	// 创建 priorityList 的映射，用于快速查找
	priorityMap := make(map[string]*data_frame.ItemData[Item])

	// 按类型分组处理 priorityList
	priorityTypeMap := lo.GroupBy(priorityList, func(item *data_frame.ItemData[Item]) string {
		switch item.GetBizItem().GetItemMeta().DocType {
		case content.DocType_Answer, content.DocType_Article, content.DocType_Paper, content.DocType_ZhiDaUserUpload, content.DocType_Webpage, content.DocType_CrawlerWebpage:
			return "insite_doc"
		case content.DocType_Member:
			return "author"
		}
		return "outsite_doc"
	})

	// 处理站内文档
	for _, item := range priorityTypeMap["insite_doc"] {
		docId := item.GetBizItem().GetItemMeta().DocId
		docType := item.GetBizItem().GetItemMeta().DocType
		uniqueKey := fmt.Sprintf("docId:%d-docType:%s", docId, docType)
		priorityMap[uniqueKey] = item
	}

	// 处理创作者
	for _, item := range priorityTypeMap["author"] {
		authorId := item.GetBizItem().GetItemMeta().AuthorId
		uniqueKey := fmt.Sprintf("authorId:%d", authorId)
		priorityMap[uniqueKey] = item
	}

	// 处理站外文档
	for _, item := range priorityTypeMap["outsite_doc"] {
		url := item.GetBizItem().GetItemMeta().Url
		if url != "" {
			uniqueKey := fmt.Sprintf("url:%s", url)
			priorityMap[uniqueKey] = item
		}
	}

	// 按类型分组处理 secondaryList
	secondaryTypeMap := lo.GroupBy(secondaryList, func(item *data_frame.ItemData[Item]) string {
		switch item.GetBizItem().GetItemMeta().DocType {
		case content.DocType_Answer, content.DocType_Article, content.DocType_Paper, content.DocType_ZhiDaUserUpload, content.DocType_Webpage, content.DocType_CrawlerWebpage:
			return "insite_doc"
		case content.DocType_Member:
			return "author"
		}
		return "outsite_doc"
	})

	// 过滤 secondaryList，如果与 priorityList 重复则跳过
	var filteredSecondaryList []*data_frame.ItemData[Item]

	// 处理站内文档
	for _, item := range secondaryTypeMap["insite_doc"] {
		docId := item.GetBizItem().GetItemMeta().DocId
		docType := item.GetBizItem().GetItemMeta().DocType
		uniqueKey := fmt.Sprintf("docId:%d-docType:%s", docId, docType)
		if _, exists := priorityMap[uniqueKey]; !exists {
			filteredSecondaryList = append(filteredSecondaryList, item)
		}
	}

	// 处理创作者
	for _, item := range secondaryTypeMap["author"] {
		authorId := item.GetBizItem().GetItemMeta().AuthorId
		uniqueKey := fmt.Sprintf("authorId:%d", authorId)
		if _, exists := priorityMap[uniqueKey]; !exists {
			filteredSecondaryList = append(filteredSecondaryList, item)
		}
	}

	// 处理站外文档
	for _, item := range secondaryTypeMap["outsite_doc"] {
		url := item.GetBizItem().GetItemMeta().Url
		if url != "" {
			uniqueKey := fmt.Sprintf("url:%s", url)
			if _, exists := priorityMap[uniqueKey]; !exists {
				filteredSecondaryList = append(filteredSecondaryList, item)
			}
		}
	}

	return filteredSecondaryList
}
