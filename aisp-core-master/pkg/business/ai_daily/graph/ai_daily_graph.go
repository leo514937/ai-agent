package graph

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

func AIDailyPlaylistGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("ai_daily_graph", graph_constant.ApiAIDailyPlaylist+".all", "1.6")

	//================流程声明================
	// **********准备阶段，参数校验********
	var prepareStage = zagHandler.NewZagStageDeclare(conf.StagePrepare)
	var prepareLogic = zagHandler.NewZagLogicDeclare(conf.LogicPrepare).SetClass(logic.PrepareLogic{})
	prepareStage.AddLogics(prepareLogic)

	// **********查询今日精选快照**********
	var querySnapshotStage = zagHandler.NewZagStageDeclare(conf.StageQueryPlaylist).AddPres(prepareStage)
	var getPlaylistLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetPlaylist).SetClass(logic.GetPlaylistLogic{})
	querySnapshotStage.AddLogics(getPlaylistLogic)

	// **********解析快照，获取作者信息、管控等内容*********
	var parseSnapshotStage = zagHandler.NewZagStageDeclare(conf.StageParsePlaylist).AddPres(querySnapshotStage)
	var parseBeginLogic = zagHandler.NewZagLogicDeclare(conf.LogicParseBegin).SetClass(empty.EmptyBaseLogic{})
	// 反序列化快照
	var parsePlaylistLogic = zagHandler.NewZagLogicDeclare(conf.LogicParsePlaylist).SetClass(logic.ParsePlaylistLogic{}).AddPreLogic(parseBeginLogic)
	// 获取用户数据
	var getUserInfoLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetUserInfo).SetClass(logic.GetUserInfoLogic{}).AddPreLogic(parseBeginLogic)
	var getAnswerAuthorLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetAuthorName).SetClass(logic.GetAnswerAuthorLogic{}).AddPreLogic(parsePlaylistLogic)
	// 解析快照后的数据管控
	var contentRegulateAfterParseLogic = zagHandler.NewZagLogicDeclare(conf.LogicContentRegulateAfterParse).SetClass(logic.ContentRegulateLogic{}).AddConfig(conf.Stage, conf.StageParsePlaylist).AddPreLogic(parsePlaylistLogic)
	// 解析快照后的安全管控
	var securityRegulateAfterParseLogic = zagHandler.NewZagLogicDeclare(conf.LogicSecurityAfterParse).SetClass(logic.SecurityRegulateLogic{}).AddConfig(conf.Stage, conf.StageParsePlaylist).AddPreLogic(parsePlaylistLogic)
	parseSnapshotStage.AddLogics(parseBeginLogic, parsePlaylistLogic, getUserInfoLogic, getAnswerAuthorLogic, contentRegulateAfterParseLogic, securityRegulateAfterParseLogic)

	// **********生成今日精选数据*********
	var getDataStage = zagHandler.NewZagStageDeclare(conf.StageGetData).AddPres(querySnapshotStage)
	// 查询用户兴趣
	var getThemeLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetTheme).SetClass(logic.GetThemeLogic{})
	// 根据兴趣ID查询问题
	var getQuestionByThemeLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetQuestionByTheme).SetClass(logic.GetQuestionByThemeIDLogic{}).AddPreLogic(getThemeLogic)
	// 查询热度最高的问题
	var getMostLikeQuestionLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetMostLikeQuestion).SetClass(logic.GetMostLikeQuestionsLogic{}).AddPreLogic(getThemeLogic)
	// 查询用户已读的问题
	var getViewedQuestionLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetViewedQuestion).SetClass(logic.GetViewedQuestionsLogic{}).AddPreLogic(getThemeLogic)
	// 查询用户感兴趣的高维标签对应的questionIDs
	var getQuestionByHighLabelsLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetQuestionByHighLabels).SetClass(logic.GetQuestionByHighLabelsLogic{}).AddPreLogic(getThemeLogic)
	// 查询问题详情
	var getQuestionDetailLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetQuestionDetail).SetClass(logic.GetQuestionDetailLogic{}).AddPreLogic(getQuestionByThemeLogic).AddPreLogic(getMostLikeQuestionLogic).AddPreLogic(getViewedQuestionLogic).AddPreLogic(getQuestionByHighLabelsLogic)
	getDataStage.AddLogics(getThemeLogic, getQuestionByThemeLogic, getMostLikeQuestionLogic, getQuestionByHighLabelsLogic, getViewedQuestionLogic, getQuestionDetailLogic)

	// **********数据过滤，相似度过滤、管控过滤等*********
	var filterStage = zagHandler.NewZagStageDeclare(conf.StageFilter).AddPres(getDataStage)
	// 计算问题相似度
	var calcQuestionSimLogic = zagHandler.NewZagLogicDeclare(conf.LogicCalcQuestionSim).SetClass(logic.CalcQuestionSimLogic{})
	// 计算兴趣相似度
	var calcThemeSimLogic = zagHandler.NewZagLogicDeclare(conf.LogicCalcThemeSim).SetClass(logic.CalcThemeSimLogic{})
	// 内容管控
	var contentRegulateLogic = zagHandler.NewZagLogicDeclare(conf.LogicContentRegulate).SetClass(logic.ContentRegulateLogic{}).AddConfig(conf.Stage, conf.StageFilter)
	// 安全侧管控
	var securityRegulateLogic = zagHandler.NewZagLogicDeclare(conf.LogicSecurityRegulate).SetClass(logic.ContentRegulateLogic{}).AddConfig(conf.Stage, conf.StageFilter)
	// 获取过滤后的数据
	var getDataAfterFilterLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetDataAfterFilter).SetClass(logic.GetDataAfterFilterLogic{}).AddPreLogic(calcQuestionSimLogic).AddPreLogic(calcThemeSimLogic).AddPreLogic(contentRegulateLogic).AddPreLogic(securityRegulateLogic)
	filterStage.AddLogics(calcQuestionSimLogic, calcThemeSimLogic, contentRegulateLogic, securityRegulateLogic, getDataAfterFilterLogic)

	// **********数据生成，落库等*********
	var generateSnapshotStage = zagHandler.NewZagStageDeclare(conf.StageGenerateSnapshot).AddPres(filterStage)
	// 选择最终下发的问题
	var selectDataLogic = zagHandler.NewZagLogicDeclare(conf.LogicSelectData).SetClass(logic.SelectDataLogic{})
	// 获取下发的问题中answer的作者名
	var getAnswerAuthorInfoLogic = zagHandler.NewZagLogicDeclare(conf.LogicGetAuthorInfoName).SetClass(logic.GetAnswerAuthorLogic{}).AddPreLogic(selectDataLogic)
	// 保存快照
	var savePlaylistLogic = zagHandler.NewZagLogicDeclare(conf.LogicSavePlaylist).SetClass(logic.SavePlaylistLogic{}).AddPreLogic(selectDataLogic)
	// question写TiDB
	var saveTiDBQuestionLogic = zagHandler.NewZagLogicDeclare(conf.LogicSaveTiDB).SetClass(logic.SaveTiDBQuestionLogic{}).AddPreLogic(selectDataLogic)
	// 写rucene
	var saveRuceneLogic = zagHandler.NewZagLogicDeclare(conf.LogicSaveRucene).SetClass(logic.SaveRuceneLogic{}).AddPreLogic(selectDataLogic)
	generateSnapshotStage.AddLogics(selectDataLogic, getAnswerAuthorInfoLogic, savePlaylistLogic, saveTiDBQuestionLogic, saveRuceneLogic)

	// **********响应数据*********
	var responseStage = zagHandler.NewZagStageDeclare(conf.StageResponse).AddPres(generateSnapshotStage).AddPres(parseSnapshotStage).AddPres(prepareStage)
	var packageResponseLogic = zagHandler.NewZagLogicDeclare(conf.LogicPackageResponse).SetClass(logic.PackageResponseLogic{})
	responseStage.AddLogics(packageResponseLogic)

	//条件依赖
	//prepareLogic
	prepareLogic.SetSelectEdge(map[string][]string{
		"Normal": {getPlaylistLogic.Name},
		"Return": {packageResponseLogic.Name},
	})
	//getPlaylistLogic
	getPlaylistLogic.SetSelectEdge(map[string][]string{
		"Generate": {getThemeLogic.Name},
		"Parse":    {parseBeginLogic.Name},
		"Return":   {packageResponseLogic.Name},
	})

	stages := []*zagHandler.DeclareStage{
		prepareStage, querySnapshotStage, parseSnapshotStage, getDataStage, filterStage, generateSnapshotStage, responseStage,
	}

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stages...)
	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}
