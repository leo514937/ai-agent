package main

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/personal_knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
)

// go run pkg/tools/biz/knowledge_base/main.go
func main() {
	ctx := context.Background()
	bizService := grpc.NewAispBizService()
	internalKnowledgeBaseService := service.NewInternalKnowledgeBaseServiceImpl()
	knowledgebaseDao := daoImpl.DefaultKnowledgeBaseV2DaoImpl

	insertBaseRes, err := bizService.BuildPersonalKnowledgeBaseIndex(ctx, &proto.BuildPersonalKnowledgeBaseIndexRequest{
		MemberId:          117223006,
		KnowledgeBaseId:   30,
		KnowledgeBaseName: "我的圣诞节礼物",
		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_FOLDER,
		ActionType:        proto.KbActionType_AT_INSERT,
	})
	fmt.Println(fmt.Sprintf("res:%s, err:%v", util.GetJSONIgnoreError(insertBaseRes), err))

	insertDocRes, err := bizService.BuildPersonalKnowledgeBaseIndex(ctx, &proto.BuildPersonalKnowledgeBaseIndexRequest{
		MemberId:          117223006,
		DocId:             1829975511776026624,
		DocType:           proto.DocType_PAPER,
		KnowledgeBaseId:   200,
		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_FOLDER,
		ActionType:        proto.KbActionType_AT_INSERT,
		Scene:             proto.KnowledgeBaseScene_PERSONAL_ZHIDA,
		Visibility:        proto.KnowledgeBaseVisibility_PUBLIC_FEATURE,
	})
	fmt.Println(fmt.Sprintf("res:%s, err:%v", util.GetJSONIgnoreError(insertDocRes), err))

	delDocRes, err := bizService.BuildPersonalKnowledgeBaseIndex(ctx, &proto.BuildPersonalKnowledgeBaseIndexRequest{
		MemberId:          117223006,
		DocId:             1828559338408701952,
		DocType:           proto.DocType_PAPER,
		KnowledgeBaseId:   30,
		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_FOLDER,
		ActionType:        proto.KbActionType_AT_DELETED,
		Scene:             proto.KnowledgeBaseScene_PERSONAL_ZHIDA,
	})
	fmt.Println(fmt.Sprintf("res:%s, err:%v", util.GetJSONIgnoreError(delDocRes), err))

	delBaseRes, err := bizService.BuildPersonalKnowledgeBaseIndex(ctx, &proto.BuildPersonalKnowledgeBaseIndexRequest{
		MemberId:          117223006,
		KnowledgeBaseId:   20,
		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_FOLDER,
		ActionType:        proto.KbActionType_AT_DELETED,
	})
	fmt.Println(fmt.Sprintf("res:%s, err:%v", util.GetJSONIgnoreError(delBaseRes), err))

	renameBaseRes, err := bizService.BuildPersonalKnowledgeBaseIndex(ctx, &proto.BuildPersonalKnowledgeBaseIndexRequest{
		MemberId:          117223006,
		KnowledgeBaseId:   30,
		KnowledgeBaseName: "我的圣诞节专享计划",
		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_FOLDER,
		ActionType:        proto.KbActionType_AT_UPDATE,
	})
	fmt.Println(fmt.Sprintf("res:%s, err:%v", util.GetJSONIgnoreError(renameBaseRes), err))

	resDoc, err := bizService.KbRecallSearch(ctx, &proto.KbRecallSearchRequest{
		MemberId:         117223006,
		Query:            "推荐算法",
		RecallSearchType: proto.KbRecallSearchType_RST_DOC,
		KnowledgeBaseType: []proto.PersonalKnowledgeBaseType{
			proto.PersonalKnowledgeBaseType_PKB_FOLDER,
			proto.PersonalKnowledgeBaseType_PKB_RSS,
			proto.PersonalKnowledgeBaseType_PKB_FAV,
		},
		SearchRecallField: []proto.KbRecallSearchField{
			proto.KbRecallSearchField_RSF_TITLE,
			proto.KbRecallSearchField_RSF_ABSTRACT,
			proto.KbRecallSearchField_RSF_CONTENT,
		},
		Limit: 100,
	})
	fmt.Println(fmt.Sprintf("searchPersonalKnowledgeDoc:%s ,err:%v", util.GetJSONIgnoreError(resDoc), err))

	resBase, err := bizService.KbRecallSearch(ctx, &proto.KbRecallSearchRequest{
		//MemberId:         117223006,
		Query:            "推荐",
		RecallSearchType: proto.KbRecallSearchType_RST_FOLDER,
		KnowledgeBaseType: []proto.PersonalKnowledgeBaseType{
			proto.PersonalKnowledgeBaseType_PKB_FAV,
			proto.PersonalKnowledgeBaseType_PKB_FOLDER,
			proto.PersonalKnowledgeBaseType_PKB_RSS,
		},
		SearchRecallField: []proto.KbRecallSearchField{
			proto.KbRecallSearchField_RSF_TITLE,
			proto.KbRecallSearchField_RSF_DESCRIPTION,
		},
		Visibility: proto.KnowledgeBaseVisibility_PUBLIC_FEATURE,
	})
	fmt.Println(fmt.Sprintf("searchPersonalKnowledgeBase:%s ,err:%v", util.GetJSONIgnoreError(resBase), err))
	//
	//// ------------ 内部文档知识库 ------------
	//
	delErr := knowledgebaseDao.DeleteKnowledgeBase(ctx, 3644203052002443265)
	fmt.Println(fmt.Sprintf("DeleteKnowledgeBase:%v", delErr))

	createErr := internalKnowledgeBaseService.CreateKnowledgeBase(ctx, &model.KnowledgeBase{
		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_INTERNAL,
		KnowledgeBaseName: "机器学习平台测试知识库",
		CreatorUserId:     "wangran",
		BizGroup:          proto.BizGroup_MACHINE_LEARNING_PLATFORM.String(),
	})
	fmt.Println(fmt.Sprintf("CreateKnowledgeBase:%v", createErr))

	resUpsertDoc, err := bizService.UpsertKnowledgeBaseDocument(ctx, &proto.UpsertKnowledgeBaseDocumentRequest{
		DocIdentity: &proto.DocIdentity{
			DocId:   3644220504180523009,
			DocType: proto.DocType_INTERNAL_DOC,
		},
		DocMeta: &proto.DocMeta{
			Title:           "整体架构规划",
			Abstract:        "主体模块说明",
			Content:         "klara-console：平台 UI 控制台；\nklara-data：提供数据的存储、转换、管理能力，提供模型训练数据集；\nklara-dev：提供模型开发支持，jupyter / vscode 等；\nklara-train：提供模型分布式训练、超参优化、模型导出等能力；\nklara-model：提供模型的版本管理、推理服务部署管理、模型镜像市场等能力；\nklara-serving：提供多框架在线推理服务支持、自定义推理服务、REST/GRPC 调用接口等；\n",
			LastUpdatedTime: 1677945600,
			Url:             "https://wiki.in.zhihu.com/pages/viewpage.action?pageId=340008606",
			Tags:            []string{"规划"},
			AuthorityLevel:  proto.AuthorityLevel_A,
			Source:          "wiki",
		},
		BizGroup: proto.BizGroup_MACHINE_LEARNING_PLATFORM,
		Operator: "wangran",
	})
	fmt.Println(fmt.Sprintf("UpsertKnowledgeBaseDocument:%s ,err:%v", util.GetJSONIgnoreError(resUpsertDoc), err))

	insertDocRes2, err := bizService.BuildPersonalKnowledgeBaseIndex(ctx, &proto.BuildPersonalKnowledgeBaseIndexRequest{
		MemberId:          0,
		DocId:             3644220504180523009,
		DocType:           proto.DocType_INTERNAL_DOC,
		KnowledgeBaseId:   3644234844440887298,
		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_INTERNAL,
		ActionType:        proto.KbActionType_AT_INSERT,
		Scene:             proto.KnowledgeBaseScene_INTERNAL_DOCUMENT,
	})
	fmt.Println(fmt.Sprintf("res:%s, err:%v", util.GetJSONIgnoreError(insertDocRes2), err))

}
