package conf_stage

import (
	"context"
	"fmt"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_biz_ext/paper_biz_ext"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources/ab"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

type StageRecallConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
}

func (c *StageRecallConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 默认关闭所有召回
	logicConfigMap := map[string]map[string]string{
		// 挂载文档召回
		stream_chat_default_tab_conf.MountDoc2SpecifiedDocRecallLogic: {
			conf.BaseConfigSkip: "true",
		},
		// 挂载答主召回
		stream_chat_default_tab_conf.KbZhihuAuthorDocRecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				RecallSize:        16,
				Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
				KnowledgeBaseType: enums.KnowledgeBaseTypeAuthor,
				RestrictedScope: searchThrift.RestrictedScope{
					RestrictedScene: macro.RestrictedSceneMember,
					RestrictedField: macro.RestrictedFieldMemberId,
					RestrictedValue: `{{.AuthorIds}}`,
				},
			}),
		},
		// 论文召回
		stream_chat_default_tab_conf.KbPaperRecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				RecallSize:        16,
				KnowledgeBaseType: enums.KnowledgeBaseTypePaper,
				Vertical:          []searchThrift.Vertical{searchThrift.Vertical_DomesticScholar, searchThrift.Vertical_ForeignScholar},
			}),
		},
		stream_chat_default_tab_conf.KbReplenishArxivRecallLogic: {
			conf.BaseConfigSkip:    "true",
			conf.ConfigRecallSize:  "16",
			conf.KnowledgeBaseType: enums.KnowledgeBaseTypePaper.String(),
		},
		// 站外召回
		stream_chat_default_tab_conf.KbBingRecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal,
				RecallSize:        16,
			}),
		},
		stream_chat_default_tab_conf.KbSerperRecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal,
				RecallSize:        16,
			}),
		},
		stream_chat_default_tab_conf.KbQuarkRecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal,
				RecallSize:        16,
			}),
		},
		stream_chat_default_tab_conf.KbKexinRecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal,
				RecallSize:        16,
			}),
		},
		stream_chat_default_tab_conf.KbOutSiteRuceneRecallLogic: {
			conf.BaseConfigSkip:    "true",
			conf.ConfigRecallSize:  "10",
			conf.KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal.String(),
		},
		stream_chat_default_tab_conf.KbOutSiteRumRecallLogic: {
			conf.BaseConfigSkip:    "true",
			conf.ConfigRecallSize:  "10",
			conf.KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal.String(),
		},
		// 站内召回
		stream_chat_default_tab_conf.KbZhihuRecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				RecallSize:        16,
				KnowledgeBaseType: enums.KnowledgeBaseTypeZhihu,
				Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
			}),
		},
		stream_chat_default_tab_conf.KbZhihuA4RecallLogic: {
			conf.BaseConfigSkip: "true",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				RecallSize:        16,
				KnowledgeBaseType: enums.KnowledgeBaseTypeZhihu,
				OnlyA4p:           true,
				Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
			}),
		},
		// 个人知识库召回(自行判断知识库类型)
		stream_chat_default_tab_conf.PersonalKnowledgeBaseRumRecallLogic: {
			conf.BaseConfigSkip:   "true",
			conf.ConfigRecallSize: "16",
		},
		stream_chat_default_tab_conf.PersonalKnowledgeBaseRuceneRecallLogic: {
			conf.BaseConfigSkip:   "true",
			conf.ConfigRecallSize: "16",
		},
		// 创作者召回
		stream_chat_default_tab_conf.AuthorSearchRecallLogic: {
			conf.BaseConfigSkip:   "true",
			conf.ConfigRecallSize: "16",
		},
		stream_chat_default_tab_conf.AuthorSearchSelfRecallLogic: {
			conf.BaseConfigSkip:   "true",
			conf.ConfigRecallSize: "16",
		},
		// 内部文档召回
		stream_chat_default_tab_conf.InternalKnowledgeBaseRumRecallLogic: {
			conf.BaseConfigSkip:    "true",
			conf.ConfigRecallSize:  "4",
			conf.KnowledgeBaseType: enums.KnowledgeBaseTypePersonalFolder.String(),
		},
		stream_chat_default_tab_conf.InternalKnowledgeBaseRuceneRecallLogic: {
			conf.BaseConfigSkip:    "true",
			conf.ConfigRecallSize:  "8",
			conf.KnowledgeBaseType: enums.KnowledgeBaseTypePersonalFolder.String(),
		},

		// ===
		// 其他merge 配置
		stream_chat_default_tab_conf.KbZhihuAuthorDocSourceMergeLogic: {
			conf.RecallMergeTopK:            "16",
			conf.RecallMergeScoreThreshold:  "0.0",
			conf.RecallMergeScoreTextField:  enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSimilarScore)),
		},
		stream_chat_default_tab_conf.KbRecallPaperSourceMergeLogic: {
			conf.RecallMergeTopK:           "16",
			conf.RecallMergeScoreThreshold: "0.7",
			conf.RecallMergeScoreTextField: enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeScoreTextSourceField: strings.Join([]string{
				fmt.Sprintf("%s:%s", conf.KbSourceZhihuArxiv, enums.SimilarTextTypeByTitleAndAbstract.String()),
				fmt.Sprintf("%s:%s", conf.KbSourceZhihuWeipu, enums.SimilarTextTypeByTitleAndAbstract.String()),
			}, ";"),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSimilarScore)),
		},
		stream_chat_default_tab_conf.KbRecallOutSiteSourceMergeLogic: {
			conf.RecallMergeTopK:            "5",
			conf.RecallMergeScoreThreshold:  "0.95",
			conf.RecallMergeScoreTextField:  enums.SimilarTextTypeByTitle.String(),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSimilarScore)),
		},
		stream_chat_default_tab_conf.KbRecallZhihuSourceMergeLogic: {
			conf.RecallMergeTopK:            "16",
			conf.RecallMergeScoreThreshold:  "0",
			conf.RecallMergeScoreTextField:  enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeModel:           string(rpc.KlaraServiceUrlBgeRerank),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSimilarScore)),
		},
		stream_chat_default_tab_conf.PersonalKnowledgeBaseMergeLogic: {
			conf.RecallMergeTopK:            "16",
			conf.RecallMergeScoreThreshold:  "0.5",
			conf.RecallMergeScoreTextField:  enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSimilarScore)),
		},
		stream_chat_default_tab_conf.InternalKnowledgeBaseRecallSimMergeLogic: {
			conf.RecallMergeTopK:            "16",
			conf.RecallMergeScoreThreshold:  "0.7",
			conf.RecallMergeScoreTextField:  enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSimilarScore)),
		},
		stream_chat_default_tab_conf.AuthorSearchMergeLogic: {
			conf.AuthorSearchAgentRankBeta: "0.5",
			conf.RecallMergeTopK:           "16",
			conf.RecallMergeGuarantee:      "author_self:1",
			conf.RecallMergeScoreThreshold: "0.5",
		},

		// filter
		stream_chat_default_tab_conf.SiteLevelFilterLogic: {
			conf.RecallFilterSiteLevelThreshold.ToConvert(): "3",
		},
		stream_chat_default_tab_conf.TagCoreMetaFetcherLogic: {
			conf.TagCoreSceneCode:    string(rpc.SceneCode_AiUserInterest),
			conf.TagCoreAppGroupCode: string(rpc.AppGroupCode_AiUserRecall),
		},
		stream_chat_default_tab_conf.KbZhihuRecallTagFetcherLogic: {
			conf.TagCoreSceneCode:    string(rpc.SceneCode_AiUserInterest),
			conf.TagCoreAppGroupCode: string(rpc.AppGroupCode_AiUserRecall),
		},
		stream_chat_default_tab_conf.KbRecallTagFilterLogic: {
			conf.FilterLogicConfByExtraExcludeKbSourceArr: strings.Join([]string{
				conf.KbSourceUserSpecified.String(),
			}, ","),
		},
		stream_chat_default_tab_conf.ValidContentRegulateFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Answer.String(),
				aiContent.DocType_Article.String(),
				aiContent.DocType_Paper.String(),
				aiContent.DocType_Webpage.String(),
				aiContent.DocType_ZhiDaUserUpload.String(),
				aiContent.DocType_InternalDoc.String(),
				aiContent.DocType_AispUserUpload.String(),
			}, ","),
			conf.ConfigRegulateSceneCode:    rpc.SceneCodeSearch,
			conf.ConfigRegulateSubSceneCode: rpc.SubSceneCodeDEFAULT,
		},
		stream_chat_default_tab_conf.RecallSecurityValidContentFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Answer.String(),
				aiContent.DocType_Article.String(),
				aiContent.DocType_Paper.String(),
				aiContent.DocType_Webpage.String(),
				aiContent.DocType_Text.String(),
				aiContent.DocType_Link.String(),
				aiContent.DocType_InternalDoc.String(),
				aiContent.DocType_AispUserUpload.String(),
			}, ","),
			conf.FilterLogicConfByIncludePaperArr: strings.Join([]string{
				paper_biz_ext.PaperPublishSource_Arxiv.String(),
			}, ","),
			// 附加排除 当 IncludeDocType 和 ExtraExcludeKbSource 同时满足时 附加排除kbSource
			conf.FilterLogicConfByExtraExcludeKbSourceArr: strings.Join([]string{
				conf.KbSourceUserSpecified.String(),
			}, ","),
			conf.FilterLogicConfByIsCheckFullContent: "true",
		},

		stream_chat_default_tab_conf.ContentRegulateFilterLogic: {
			conf.ConfigRegulateKey: rpc.VisitorCirculate,
			conf.FilterLogicConfByExtraExcludeKbSourceArr: strings.Join([]string{
				conf.KbSourceUserSpecified.String(),
			}, ","),
		},
		stream_chat_default_tab_conf.KbRecallSimhashFilterLogic: {
			conf.RecallFilterSimHashThreshold.ToConvert():    "0.9",
			conf.RecallFilterSimHashContentLimit.ToConvert(): "2048",
		},
	}

	customConfigMap := c.GetTrafficCustomConfig(ctx, requestCtx, user)
	customConfigMap = c.ChangeConfigByAb(ctx, requestCtx, customConfigMap)

	logicConfigMap = stage_handler.OverrideGraphStageConfig(logicConfigMap, customConfigMap)
	return logicConfigMap
}

// GetMainRecallCustomConfig 获得主召回配置
func (c *StageRecallConfig) GetMainRecallCustomConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 1. 意图为答主搜索 & 知识库里有知乎 -> 答主召回
	// 2. 其他意图（前面已排除过 wru 和模型直接回答）
	// 2.1 有挂载 - 纯文档 -> 召回当前指定文档
	// 2.2 有挂载 - 用户 -> 召回当前指定用户
	// 2.3 有挂载 - 知识库 -> 召回当前指定知识库
	// 2.4 有知识库  -> 根据知识库召回

	// 获取意图
	intention, _ := requestCtx.DataMap().GetString(ctx, graph_macro.ZagKeyIntention)
	currIntentionType := macro.IntentionType(intention)

	// 知识库
	knowledgeBases := requestCtx.GetBizContext().GetKnowledgeBases()

	// 当答主搜索意图，且知识库里含知乎时 - 只开放答主召回算子
	if currIntentionType == macro.GetQueryRouteAuthor() && lo.Contains(knowledgeBases, proto.KnowledgeBaseType_KBT_ZHIHU) {
		return map[string]map[string]string{
			stream_chat_default_tab_conf.AuthorSearchRecallLogic: {
				conf.BaseConfigSkip: "false",
			},
			stream_chat_default_tab_conf.AuthorSearchSelfRecallLogic: {
				conf.BaseConfigSkip: "false",
			},
		}
	}

	customConfig := map[string]map[string]string{}

	// 当前与历史挂载
	currentAndHistoryReferenceMount := requestCtx.GetBizContext().GetCurrentAndHistoryReferenceMount()
	// 如果挂载有Doc
	if len(currentAndHistoryReferenceMount.GetMountDocs()) > 0 {
		customConfig[stream_chat_default_tab_conf.MountDoc2SpecifiedDocRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
	}
	// 如果含有挂载用户 默认会开启挂载用户召回
	if len(currentAndHistoryReferenceMount.GetMountMembers()) > 0 {
		customConfig[stream_chat_default_tab_conf.KbZhihuAuthorDocRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
	}
	// 如果含有挂载知识库
	if len(currentAndHistoryReferenceMount.GetMountBases()) > 0 {
		// 个人知识库
		customConfig[stream_chat_default_tab_conf.PersonalKnowledgeBaseRumRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
		customConfig[stream_chat_default_tab_conf.PersonalKnowledgeBaseRuceneRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
		// 内部知识库
		customConfig[stream_chat_default_tab_conf.InternalKnowledgeBaseRumRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
		customConfig[stream_chat_default_tab_conf.InternalKnowledgeBaseRuceneRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
	}
	// 处理大知识库
	for _, knowledgeBase := range knowledgeBases {
		switch knowledgeBase {
		case proto.KnowledgeBaseType_KBT_GLOBAL:
			customConfig[stream_chat_default_tab_conf.KbQuarkRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
			customConfig[stream_chat_default_tab_conf.KbOutSiteRumRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
			customConfig[stream_chat_default_tab_conf.KbOutSiteRuceneRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
		case proto.KnowledgeBaseType_KBT_PAPER:
			customConfig[stream_chat_default_tab_conf.KbPaperRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
		case proto.KnowledgeBaseType_KBT_ZHIHU:
			customConfig[stream_chat_default_tab_conf.KbZhihuRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
			customConfig[stream_chat_default_tab_conf.KbZhihuA4RecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
		case proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE:
			customConfig[stream_chat_default_tab_conf.PersonalKnowledgeBaseRumRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
			customConfig[stream_chat_default_tab_conf.PersonalKnowledgeBaseRuceneRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
			customConfig[stream_chat_default_tab_conf.InternalKnowledgeBaseRumRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
			customConfig[stream_chat_default_tab_conf.InternalKnowledgeBaseRuceneRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
		}
	}

	return customConfig
}

func (c *StageRecallConfig) ChangeConfigByAb(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], customConfigMap map[string]map[string]string) map[string]map[string]string {
	// 直答全网召回替换实验，如果 zhida 场景 && 实验组 && quark 召回开启，则关闭 quark 召回并开启可信召回
	if requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_zhida && requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdAiRecDomain).GetZlabAB(ab.QuarkToKexinExp1) {
		if logicConfig, exist := customConfigMap[stream_chat_default_tab_conf.KbQuarkRecallLogic]; exist && logicConfig[conf.BaseConfigSkip] == "false" {
			customConfigMap[stream_chat_default_tab_conf.KbQuarkRecallLogic][conf.BaseConfigSkip] = "true"
			customConfigMap[stream_chat_default_tab_conf.KbKexinRecallLogic] = map[string]string{
				conf.BaseConfigSkip: "false",
			}
		}
	}
	return customConfigMap
}

// GetTrafficCustomConfig 获取流量自定义配置
func (c *StageRecallConfig) GetTrafficCustomConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 获取意图
	intention, _ := requestCtx.DataMap().GetString(ctx, graph_macro.ZagKeyIntention)
	currIntentionType := macro.IntentionType(intention)
	// 意图=WRU 没有任何召回
	if currIntentionType == macro.GetQueryRouteIdentity() {
		return map[string]map[string]string{}
	}
	// 意图=模型直接回答 && 不是纯文档挂载， 则没有任何召回
	if currIntentionType == macro.GetQueryRouteDirect() && !requestCtx.GetBizContext().GetCurrReferenceMount().IsMountPureDoc() {
		return map[string]map[string]string{}
	}
	// 翻译-模型直接回答，无召回
	if requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_zhida_translation {
		return map[string]map[string]string{}
	}
	// 直答2.0主场景&&没有任何知识库或挂载-模型直接回答，无召回
	if requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_zhida && len(requestCtx.GetBizContext().GetKnowledgeBases()) == 0 &&
		requestCtx.GetBizContext().GetCurrReferenceMount().GetMountLength() == 0 && requestCtx.GetBizContext().GetHistoryReferenceMount().GetMountLength() == 0 {
		return map[string]map[string]string{}
	}

	switch requestCtx.GetBizContext().GetTrafficSource() {
	// 直答、直答专业版、内部QA助手、有数
	case proto.TrafficSource_undefined_traffic, proto.TrafficSource_zhida, proto.TrafficSource_zhida_knowledge_ground, proto.TrafficSource_zhida_pro,
		proto.TrafficSource_internal_qa, proto.TrafficSource_commercial_data_insight:
		return c.GetMainRecallCustomConfig(ctx, requestCtx, user)
	// 直答GR
	case proto.TrafficSource_zhida_gr_demo:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.KbZhihuRecallLogic: {
				conf.BaseConfigSkip: "false",
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
					OrderGroup:        0,
					RecallSize:        16,
					KnowledgeBaseType: enums.KnowledgeBaseTypeZhihu,
					Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
				}),
			},
		}
		return customConfig
	// 解释-只用知乎召回
	case proto.TrafficSource_zhida_word_interpretation:
		return map[string]map[string]string{
			stream_chat_default_tab_conf.KbZhihuRecallLogic: {
				conf.BaseConfigSkip: "false",
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
					Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
					OrderGroup:        0,
					RecallSize:        16,
					KnowledgeBaseType: enums.KnowledgeBaseTypeZhihu,
				}),
			},
		}
	// 直答-AI摘要
	case proto.TrafficSource_zhida_summary:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.MountDoc2SpecifiedDocRecallLogic: {
				conf.BaseConfigSkip: "false",
			},
		}
		return customConfig
	// 搜索结果页无搜索结果时出直答 bar
	case proto.TrafficSource_unsatisfied_search:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.KbZhihuRecallLogic: {
				conf.BaseConfigSkip: "false",
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
					Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
					OrderGroup:        0,
					RecallSize:        16,
					KnowledgeBaseType: enums.KnowledgeBaseTypeZhihu,
				}),
			},
			stream_chat_default_tab_conf.KbQuarkRecallLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
					OrderGroup:        1,
					RecallSize:        8,
					KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal,
				}),
			},
		}
		return customConfig
	// AI 垂搜（新策略只APP生效）
	case proto.TrafficSource_search_tab:
		switch requestCtx.GetBizContext().GetClientSource() {
		case proto.ClientSource_ZHIHU_APP:
			return c.GetMainRecallCustomConfig(ctx, requestCtx, user)
		default:
			customConfig := map[string]map[string]string{
				stream_chat_default_tab_conf.KbZhihuRecallLogic: {
					conf.BaseConfigSkip: "false",
					conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
						Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
						OrderGroup:        0,
						RecallSize:        16,
						KnowledgeBaseType: enums.KnowledgeBaseTypeZhihu,
					}),
				},
			}
			return customConfig
		}
	case proto.TrafficSource_ai_search_card_preview,
		proto.TrafficSource_ai_search_card,
		proto.TrafficSource_ai_search_card_full_search_preview,
		proto.TrafficSource_ai_search_card_full_search:
		customConfig := map[string]map[string]string{}
		customConfig[stream_chat_default_tab_conf.KbZhihuRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
		customConfig[stream_chat_default_tab_conf.KbKexinRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
		return customConfig
	case proto.TrafficSource_ai_search_general:
		customConfig := map[string]map[string]string{}
		customConfig[stream_chat_default_tab_conf.KbZhihuRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
		customConfig[stream_chat_default_tab_conf.KbKexinRecallLogic] = map[string]string{
			conf.BaseConfigSkip: "false",
		}
		customConfig[stream_chat_default_tab_conf.KbRecallZhihuSourceMergeLogic] = map[string]string{
			conf.RecallMergePriorityTagCoreKV: fmt.Sprintf("%s:%s", rpc.TagCoreAnswerProperty, rpc.TagCoreAnswerPropertyInPerson),
		}
		return customConfig
	// 其他
	default:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.KbZhihuRecallLogic: {
				conf.BaseConfigSkip: "false",
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
					Vertical:          []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
					OrderGroup:        0,
					RecallSize:        16,
					KnowledgeBaseType: enums.KnowledgeBaseTypeZhihu,
				}),
			},
		}
		return customConfig
	}
}
