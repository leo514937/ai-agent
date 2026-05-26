package main

import (
	"flag"
	"math/rand"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/tools/api/grpc_service/request"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/spf13/cast"
)

// 启动命令：
// server 端：make all;./bin/grpc-service
// client 端：go run cmd/tools/api/grpc_service/main.go
func main() {
	var (
		text          string
		host          string
		chatType      int
		buildType     int
		suggestType   int
		memberID      int64
		newSession    bool
		chatModel     int
		retryGen      bool
		chatStyle     int
		batchSize     int
		clientSource  int
		trafficSource int
		operationId   int64
		version       string
	)
	flag.StringVar(&text, "text", "hello world", "user input query")
	flag.StringVar(&host, "host", "localhost:9999", "host name")
	flag.IntVar(&chatType, "chat_type", 8, "chatType")
	flag.IntVar(&buildType, "build_type", 1, "buildType")
	flag.IntVar(&suggestType, "suggest_type", 6, "suggestType")
	flag.IntVar(&chatStyle, "chat_style", 1, "0: 默认，1：深入，2：精简")
	flag.Int64Var(&memberID, "member_id", 33328866, "member id")
	flag.BoolVar(&newSession, "new_session", true, "create new session")
	flag.BoolVar(&retryGen, "retry_gen", false, "is retry generate")
	flag.IntVar(&chatModel, "model", 1, "选择模型 0: 通用模型 1: deepseek r1  2: qwq32b")
	flag.IntVar(&batchSize, "batch_size", 1, "协程批次")
	flag.IntVar(&clientSource, "client_source", 0, "客户端来源 0未知 1WEB ...")
	flag.IntVar(&trafficSource, "traffic_source", 0, "流量来源 0未知 1直答 2搜索 ...")
	flag.Int64Var(&operationId, "operation_id", 0, "操作ID")
	flag.StringVar(&version, "version", "v2", "直答版本")
	flag.Parse()

	sessionID := "13333333333"
	if newSession {
		sessionID = cast.ToString(rand.Int63())
	}

	var messageGroupId int64
	if retryGen {
		messageGroupId = 7484526082494924580
	}
	extraInfo := &proto.ExtraInfo{
		DocQaExtraInfo: &proto.DocQaExtraInfo{
			DocId:       662342798,
			ContentType: "ANSWER",
			Paragraphs: []*proto.DocQaExtraParagraphInfo{
				{
					ParagraphIndex:   3,
					ParagraphVersion: "",
				},
				{
					ParagraphIndex:   4,
					ParagraphVersion: "",
				},
			},
		},
	}

	txn, ctx := log.StartTransaction("tools_api_grpc_service")
	defer txn.End(ctx)

	//// 创建 Session
	sessionRequest := request.NewCreateSessionRequest(host, proto.ChatType(chatType), memberID, &proto.ExtraInfo{
		ShareSessionId:  3603656719371959213,
		ShareMessageIds: []int64{7380289014434286102},
		//ShareEndMessageId: 7380289014434286102,
	}, nil)
	sessionRequest.DoCreateSessionRequest(ctx)
	// 分别从两个rum 表中获取引导词
	wg := safe_group.NewGroup("runCase")
	for i := 0; i < batchSize; i++ {
		wg.Go(func() error {
			// 模拟发起 StreamChat 请求
			chatRequest := request.NewStreamChatRequest(
				host, text, proto.ChatType(chatType), sessionID, memberID,
				proto.ChatStyle(chatStyle), proto.ClientSource(clientSource), proto.TrafficSource(trafficSource),
				&proto.DocAboutQueriesRequest{
					DocId:   681680326,
					DocType: proto.DocType_ANSWER,
				})

			var knowledgeBases = []proto.KnowledgeBaseType{
				proto.KnowledgeBaseType_KBT_GLOBAL,
				proto.KnowledgeBaseType_KBT_ZHIHU,
				proto.KnowledgeBaseType_KBT_PAPER,
				proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE,
			}

			var currMounts = []*proto.ReferenceMount{
				//{
				//	MountText: &proto.MountText{
				//		Text: "OPSLI快速开发平台是一款基于Java生态的低代码开发工具，旨在通过前后端分离架构和模块化设计简化企业级应用开发流程。该平台以\"减少重复工作、聚焦业务逻辑\"为核心目标，已在GitHub开源并提供完整的企业级解决方案[参考文献:7][参考文献:11][参考文献:12]。\n\n### 核心技术架构\nOPSLI采用分层设计的技术架构，主要包括：\n- **前端框架**：基于Vue.js和Element-UI组件库，整合vue-admin-beautiful作为基础模板，支持可视化页面配置与响应式布局[参考文献:7][参考文献:12]\n- **后端技术**：Spring Boot 2.7.x作为核心框架，集成MyBatis-Plus数据访问层、Shiro安全框架和Redis缓存，支持多数据源动态切换[参考文献:11][参考文献:12]\n- **数据库支持**：兼容MySQL、Oracle等主流关系型数据库，通过Druid连接池优化数据访问性能[参考文献:12]\n- **部署模式**：支持单机部署与集群扩展，提供Docker容器化部署方案[参考文献:11]\n\n### 关键功能特性\n1. **代码生成与可视化开发**\n   - 内置基于Jfinal Enjoy模板引擎的代码生成器，可在线生成前后端完整代码\n   - 支持自定义模板扩展，满足个性化代码风格需求[参考文献:12]\n   - 提供表单设计器、列表设计器等可视化工具，减少70%重复编码工作[参考文献:11]\n\n2. **安全与权限管理**\n   - 基于Spring Security实现多维度认证体系，支持账号密码、手机验证码等登录方式\n   - 细粒度权限控制覆盖菜单、按钮及数据级权限，支持多租户SaaS模式[参考文献:12]\n   - 数据传输采用双向加密，缓存层实现防穿透、防击穿、防雪崩策略[参考文献:12]\n\n3. **系统集成能力**\n   - 内置Knife4j实现API文档自动生成与在线调试\n   - 支持RESTful风格接口设计，提供版本控制机制确保接口兼容性[参考文献:12]\n   - 集成EasyExcel实现复杂报表导入导出，支持大数据量分批处理[参考文献:11]\n\n4. **扩展性设计**\n   - 热插拔式插件架构允许功能模块动态加载与卸载\n   - 提供事件总线机制实现模块间松耦合通信[参考文献:7][参考文献:11]\n   - 支持自定义注解扩展业务逻辑，如数据脱敏、操作日志等横切关注点[参考文献:12]\n\n### 应用场景与局限\n该平台适用于企业管理系统、后台运营平台、SaaS应用等场景，尤其适合中小团队快速构建MVP产品。根据实际用户反馈，平台在标准化业务场景下可提升3-5倍开发效率，但在高度定制化的复杂业务逻辑实现上仍存在灵活性限制[参考文献:9][参考文献:11]。\n\n### 开源与社区支持\nOPSLI采用Apache License 2.0开源协议，代码托管于GitHub(hiparker/opsli-boot)，提供完整的文档中心和在线演示环境。官方维护QQ交流群(724850675)并定期发布更新，最新稳定版本为v2.0，已支持多租户、API版本控制等企业级特性[参考文献:7][参考文献:12]。\n\n需要注意的是，作为一款开源工具，其生态完善度和商业支持与主流商业平台存在差距，企业在选型时需综合评估团队技术栈匹配度和长期维护成本。",
				//	},
				//},
				//{
				//	MountDoc: &proto.DocIdentity{
				//		DocId:   560188,
				//		DocType: proto.DocType_MEMBER,
				//	},
				//},
				//{
				//	MountDoc: &proto.DocIdentity{
				//		DocId:   246248568,
				//		DocType: proto.DocType_MEMBER,
				//	},
				//},
				//{
				//	MountBase: &proto.PersonalKnowledgeBase{
				//		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_RSS,
				//	},
				//},
				//{
				//	MountBase: &proto.PersonalKnowledgeBase{
				//		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_FOLDER,
				//		KnowledgeBaseId:   7545775141712589296,
				//	},
				//},
				//// -------------------------------------
				//// 挂载纯文档测试文档
				//{
				//	MountDoc: &proto.DocIdentity{
				//		DocId:   716037944,
				//		DocType: proto.DocType_ANSWER,
				//	},
				//},
				//{
				//	MountDoc: &proto.DocIdentity{
				//		DocId:   1002300006973577705,
				//		DocType: proto.DocType_ZHI_DA_USER_UPLOAD,
				//	},
				//},
				//{
				//	MountDoc: &proto.DocIdentity{
				//		DocId:   1002300006900916237,
				//		DocType: proto.DocType_ZHI_DA_USER_UPLOAD,
				//	},
				//},
			}
			var hisMounts = []*proto.ReferenceMount{}

			//var assignmentDocs = []*proto.ChatCardProRelevantSource{
			//{
			//	DocId:   "222842404",
			//	DocType: proto.DocType_ARTICLE,
			//},
			//{
			//	DocId:   "1827028919834042368",
			//	DocType: proto.DocType_PAPER,
			//},
			//{
			//	DocId:   "1827028920802926592",
			//	DocType: proto.DocType_ZHI_DA_USER_UPLOAD,
			//},
			//}

			//recallContentIds := []string{"403828055|:|Answer|:|https://www.zhihu.com/answer/2055606369", "662130919|:|Answer|:|"}
			recallContentIds := []string{}
			chatRequest.DoStreamChat(ctx, messageGroupId, 0, 0,
				knowledgeBases, currMounts, hisMounts, nil, proto.ChatModel(chatModel), version, recallContentIds, operationId)

			// 模拟发起 DigitalAuthor 请求
			//digitalAuthorChatRequest := request.NewDigitalAuthorChatRequest(host, text)
			//digitalAuthorChatRequest.DoDigitalAuthorChat()

			// // 模拟发起 QueryMerge 请求
			// queryMergeRequest := request.NewQueryMergeRequest(host, text, proto.BuildQueryType(buildType), sessionID, memberID)
			// queryMergeRequest.DoQueryMergeRequest()

			// // 模拟发起 词推荐 请求
			// 模拟发起 词推荐 请求
			suggestQueriesRequest := request.NewSuggestQueriesRequest(
				host, text, proto.SuggestQueriesType(suggestType), sessionID, "", memberID, extraInfo,
				proto.ClientSource(clientSource), proto.TrafficSource(trafficSource),
				&proto.DocAboutQueriesRequest{
					DocId:   682269507,
					DocType: proto.DocType_ANSWER,
				},
				[]*proto.DocAboutQueriesRequest{
					{
						DocId:   1829975511776026624,
						DocType: proto.DocType_PAPER,
					},
				},
			)
			suggestQueriesRequest.DoSuggestQueriesRequest()

			// 模拟发起 DigitalAuthor 请求
			//digitalAuthorChatRequest := request.NewDigitalAuthorChatRequest(host, text)
			//digitalAuthorChatRequest.DoDigitalAuthorChat()

			// // 模拟发起 QueryMerge 请求
			// queryMergeRequest := request.NewQueryMergeRequest(host, text, proto.BuildQueryType(buildType), sessionID, memberID)
			// queryMergeRequest.DoQueryMergeRequest()
			return nil
		})
	}
	_ = wg.Wait()
}
