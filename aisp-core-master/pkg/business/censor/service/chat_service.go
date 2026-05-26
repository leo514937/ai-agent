package service

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"strconv"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	zhihaitu_dao "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	zhihaitu_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/tracing_log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

type ChatServiceImpl struct {
	bmbConversationDao              zhihaitu_dao.BmbConversationDAO
	bmbConvMessageDAO               zhihaitu_dao.BmbConvMessageDAO
	openapiAccountDAO               zhihaitu_dao.OpenapiAccountDAO
	searchRelatedWordRecallCacheDao dao.SearchRelatedWordRecallCacheDao
	knowledgeBaseDocService         knowledge_base.KnowledgeBaseDocService
	tracingLogService               tracing_log.TracingLogService
}

func NewChatServiceImpl() *ChatServiceImpl {
	return &ChatServiceImpl{
		bmbConversationDao:              zhihaitu_dao.DefaultBmbConversationDAO,
		bmbConvMessageDAO:               zhihaitu_dao.DefaultBmbConvMessageDAO,
		openapiAccountDAO:               zhihaitu_dao.DefaultOpenapiAccountDAO,
		searchRelatedWordRecallCacheDao: daoImpl.NewSearchRelatedWordRecallCacheDao(),
		knowledgeBaseDocService:         knowledge_base.DefaultKnowledgebaseDocService,
		tracingLogService:               tracing_log.DefaultTracingLogService,
	}
}

var DefaultChatService = NewChatServiceImpl()

func dealResponseWithServiceErr(response interface{}, serviceErr *macro.ServiceError) {
	if serviceErr == nil {
		return
	}
	switch t := response.(type) {
	case *content.DisposeConversationResponse, *content.QueryQuestionDetailResponse, *content.QueryConversationDetailResponse, *content.GetWhiteListMemberIDsResponse, *content.ChatRecordQueryResponse:
		v := reflect.ValueOf(t).Elem()
		v.FieldByName("Code").SetInt(serviceErr.Code())
		v.FieldByName("Message").SetString(serviceErr.Message())
	}
}

// 处置会话
func (s *ChatServiceImpl) DisposeConversation(ctx context.Context, req *content.DisposeConversationRequest) (r *content.DisposeConversationResponse, err error) {
	r = &content.DisposeConversationResponse{
		Code:    macro.SERVICE_CODE_SUCCESS.Code(),
		Message: macro.SERVICE_CODE_SUCCESS.Message(),
	}
	var serviceErr *macro.ServiceError
	defer func() {
		if serviceErr != nil {
			dealResponseWithServiceErr(r, serviceErr)
		}
	}()
	// 查询会话
	conversation, serviceErr := s.bmbConversationDao.GetConversationByID(ctx, req.GetSessionID())
	if serviceErr != nil {
		return
	}
	// 会话状态置为删除
	updates := make(map[string]interface{})
	updates["dispose_state"] = content.QuestionState_DISPOSED
	serviceErr = s.bmbConversationDao.UpdateConversation(ctx, conversation, updates)
	if serviceErr != nil {
		return
	}
	// 消息状态置为删除
	msgUpdates := make(map[string]interface{})
	msgUpdates["is_deleted"] = zhihaitu_model.Deleted
	serviceErr = s.bmbConvMessageDAO.UpdateConvMessageByConvID(ctx, req.GetSessionID(), msgUpdates)
	if serviceErr != nil {
		return
	}
	return
}

// 查询问题信息
func (s *ChatServiceImpl) QueryQuestionDetail(ctx context.Context, req *content.QueryQuestionDetailRequest) (r *content.QueryQuestionDetailResponse, err error) {
	r = &content.QueryQuestionDetailResponse{
		Code:    macro.SERVICE_CODE_SUCCESS.Code(),
		Message: macro.SERVICE_CODE_SUCCESS.Message(),
		Data:    &content.QuestionDetail{},
	}
	var serviceErr *macro.ServiceError
	defer func() {
		if serviceErr != nil {
			dealResponseWithServiceErr(r, serviceErr)
		}
	}()
	// 查询问题消息
	convMessage, serviceErr := s.bmbConvMessageDAO.GetConvMessageByMsgID(ctx, req.GetQuestionID())
	if serviceErr != nil {
		return
	}
	// 查找用户获取user_id
	account, serviceErr := s.openapiAccountDAO.GetAccountInfoByID(ctx, convMessage.AccountID)
	if serviceErr != nil {
		return
	}
	r.Data = &content.QuestionDetail{
		SessionID:   convMessage.ConvID,
		QuestionID:  convMessage.MsgID,
		MemberID:    strconv.FormatInt(account.MemberID, 10),
		PublishTime: util.FormatTime2yyyyMMddHHmmss(convMessage.CreateTime),
		Content:     convMessage.Content,
	}
	if convMessage.StopEnum != nil && *convMessage.StopEnum == "BAN" {
		r.Data.State = content.QuestionState_DISPOSED
	} else {
		r.Data.State = content.QuestionState_NORMAL
	}
	return
}

func (s *ChatServiceImpl) ChatRecordQuery(ctx context.Context, req *content.ChatRecordRequest) (r *content.ChatRecordQueryResponse, err error) {
	r = &content.ChatRecordQueryResponse{
		Code:    macro.SERVICE_CODE_SUCCESS.Code(),
		Message: macro.SERVICE_CODE_SUCCESS.Message(),
		Data:    make([]*content.ChatRecord, 0),
	}
	var serviceErr *macro.ServiceError
	defer func() {
		if serviceErr != nil {
			dealResponseWithServiceErr(r, serviceErr)
		}
	}()

	searchRucene := &model.LogRucene{
		MemberId:            req.GetMemberID(),
		SessionId:           req.GetSessionID(),
		MessageId:           req.GetQueryID(),
		RespMessageId:       req.GetAnswerID(),
		Query:               req.GetQuery(),
		Response:            []string{req.GetAnswer()},
		RequestStartTimeMs:  req.GetRequestTimeStart() * 1000,
		RequestEndTimeMs:    req.GetRequestTimeEnd() * 1000,
		ResponseStartTimeMs: req.GetResponseTimeStart() * 1000,
		ResponseEndTimeMs:   req.GetResponseTimeEnd() * 1000,
	}
	if security, exist := securityMap[req.GetSecurity()]; exist {
		searchRucene.Security = []string{security}
	}

	searchResult, err := s.tracingLogService.SearchRucene(ctx, searchRucene)

	if err != nil {
		serviceErr = macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
		return
	}

	for _, item := range searchResult {
		// 请求时间和响应时间单位为毫秒，转换为秒
		requestTime := item.RequestTimeMs
		if util.IsMillisecond(requestTime) {
			requestTime = requestTime / 1000
		}
		responseTime := item.ResponseTimeMs
		if util.IsMillisecond(responseTime) {
			responseTime = responseTime / 1000
		}
		r.Data = append(r.Data, &content.ChatRecord{
			MemberID:     item.MemberId,
			SessionID:    item.SessionId,
			QueryID:      item.MessageId,
			AnswerID:     item.RespMessageId,
			Query:        item.Query,
			Answer:       item.GetResponse(),
			RequestTime:  requestTime,
			ResponseTime: responseTime,
			Security:     securityToSecurityMethod(item.Security),
		})
	}
	return
}

var securityMap = map[content.SecurityMethod]string{
	content.SecurityMethod_SECURITY_REFUSE: macro.SecurityReviewFailed,
	content.SecurityMethod_RED_LINE:        macro.Redline,
	content.SecurityMethod_FAQ:             macro.Faq,
}

func securityToSecurityMethod(securityTag []string) content.SecurityMethod {
	// 按照安全->红线必答->faq的顺序判断
	if lo.Contains(securityTag, macro.SecurityReviewFailed) {
		return content.SecurityMethod_SECURITY_REFUSE
	}
	if lo.Contains(securityTag, macro.Redline) {
		return content.SecurityMethod_RED_LINE
	}
	if lo.Contains(securityTag, macro.Faq) {
		return content.SecurityMethod_FAQ
	}
	return content.SecurityMethod_NONE
}

// 查询会话信息
func (s *ChatServiceImpl) QueryConversationDetail(ctx context.Context, req *content.QueryConversationDetailRequest) (r *content.QueryConversationDetailResponse, err error) {
	r = &content.QueryConversationDetailResponse{
		Code:    macro.SERVICE_CODE_SUCCESS.Code(),
		Message: macro.SERVICE_CODE_SUCCESS.Message(),
		Data: &content.ConversationDetail{
			Questions: make([]*content.QuestionDetail, 0),
			Answers:   make([]*content.AnswerDetail, 0),
		},
	}
	var serviceErr *macro.ServiceError
	defer func() {
		if serviceErr != nil {
			dealResponseWithServiceErr(r, serviceErr)
		}
	}()
	if req.GetQueryType() == content.QueryType_QUESTION {
		// 查找会话
		var conversation *zhihaitu_model.TableBmbConversation
		conversation, serviceErr = s.bmbConversationDao.GetConversationByID(ctx, req.GetSessionID())
		if serviceErr != nil {
			return
		}
		// 查找用户获取user_id
		var account *zhihaitu_model.TableOpenapiAccount
		account, serviceErr = s.openapiAccountDAO.GetAccountInfoByID(ctx, conversation.AccountID)
		if serviceErr != nil {
			return
		}
		// 查询问题
		var questionMsgs []*zhihaitu_model.TableBmbConvMessage
		questionMsgs, serviceErr = s.bmbConvMessageDAO.GetConvMessageByConvIDAndRole(ctx, req.GetSessionID(), macro.ROLE_USER)
		if serviceErr != nil {
			return
		}
		for _, v := range questionMsgs {
			questionDetail := &content.QuestionDetail{
				SessionID:   v.ConvID,
				QuestionID:  v.MsgID,
				MemberID:    strconv.FormatInt(account.MemberID, 10),
				PublishTime: util.FormatTime2yyyyMMddHHmmss(v.CreateTime),
				Content:     v.Content,
			}
			if v.StopEnum != nil && *v.StopEnum == "BAN" {
				questionDetail.State = content.QuestionState_DISPOSED
			} else {
				questionDetail.State = content.QuestionState_NORMAL
			}
			r.Data.Questions = append(r.Data.Questions, questionDetail)
		}
		return
	}
	// 查询回答
	answerMsgs, serviceErr := s.bmbConvMessageDAO.GetConvMessageByConvIDAndRole(ctx, req.GetSessionID(), macro.ROLE_AI)
	if serviceErr != nil {
		return
	}
	for _, v := range answerMsgs {
		answerDetail := &content.AnswerDetail{
			SessionID:   v.ConvID,
			QuestionID:  v.ParentMsgID,
			AnswerID:    v.MsgID,
			PublishTime: util.FormatTime2yyyyMMddHHmmss(v.CreateTime),
			AnswerType:  getAnswerType(v.MsgType),
		}
		r.Data.Answers = append(r.Data.Answers, answerDetail)
	}
	return
}

// 保存搜索召回结果缓存
func (s *ChatServiceImpl) SearchResultNotice(ctx context.Context, req *content.SearchResultNoticeRequest) (r *content.SearchResultNoticeResponse, err error) {
	contentList := req.GetRecallContentList()
	if contentList == nil || len(contentList) == 0 {
		return &content.SearchResultNoticeResponse{
			Code: 0,
		}, nil
	}

	docList := make([]model.Content, 0)
	for _, item := range contentList {
		docList = append(docList, model.NewContentWithContentType(item.GetDocId(), item.GetDocType()))
	}

	cacheErr := s.searchRelatedWordRecallCacheDao.SaveCache(ctx,
		entities.BuildGraphScene(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_SEARCH_ASK_AGAIN_RELATED.String()),
		req.GetMemberId(),
		req.GetQuery(),
		docList,
	)
	if cacheErr != nil {
		return &content.SearchResultNoticeResponse{
			Code:    500,
			Message: fmt.Sprintf("Save cache error => %s", cacheErr.Error()),
		}, cacheErr
	}
	return &content.SearchResultNoticeResponse{
		Code: 0,
	}, nil
}

func (s *ChatServiceImpl) KnowledgeBaseDocRetrieve(ctx context.Context, req *content.KnowledgeBaseDocRetrieveRequest) (*content.KnowledgeBaseDocRetrieveResponse, error) {
	retrieveResult, err := s.knowledgeBaseDocService.RetrieveKnowledgeBaseDocs(ctx, req.Query, int(req.TopK), req.DocUniqueID)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "retrieve knowledge base docs failed. query: %s", req.Query)
		return nil, err
	}

	resp := &content.KnowledgeBaseDocRetrieveResponse{
		Items: make([]*content.KnowledgeBaseDocRetrieveItem, 0),
	}

	for _, item := range retrieveResult {
		resp.Items = append(resp.Items, &content.KnowledgeBaseDocRetrieveItem{
			Text:       item.Text,
			Similarity: float64(item.Similarity),
		})
	}

	return resp, nil
}

func (s *ChatServiceImpl) KnowledgeBaseDocDetail(ctx context.Context, req *content.KnowledgeBaseDocDetailRequest) (*content.KnowledgeBaseDocDetailResponse, error) {
	docDetail, err := s.knowledgeBaseDocService.GetDocDetail(ctx, req.DocUniqueID)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "get knowledge base docs failed. docUniqueId: %s", req.DocUniqueID)
		return nil, err
	}

	var resp = &content.KnowledgeBaseDocDetailResponse{
		Text: string(docDetail),
	}

	return resp, nil
}

func getAnswerType(answerType string) content.AnswerType {
	switch answerType {
	case "conv":
		return content.AnswerType_RICH_TEXT
	default:
		return content.AnswerType_OTHER
	}
}

// 获取白名单账号列表
func (s *ChatServiceImpl) GetWhiteListMemberIDs(ctx context.Context, req *content.GetWhiteListMemberIDsRequest) (r *content.GetWhiteListMemberIDsResponse, err error) {
	r = &content.GetWhiteListMemberIDsResponse{
		Code:    macro.SERVICE_CODE_SUCCESS.Code(),
		Message: macro.SERVICE_CODE_SUCCESS.Message(),
		Data:    make([]string, 0),
	}
	r.Data = []string{"1324576569", "1324576576", "1324576583", "1324576585", "1324576590", "1324576592", "1324576595", "1324576602", "1324576606", "1324576612", "1324576616", "1324576619", "1324576621", "1324576624", "1324576626", "1324576634", "1324576637", "1324576640", "1324576644", "1324576650", "1324576655", "1324576659", "1324576665", "1324576667", "1324576669", "1324576677", "1324576680", "1324576691", "1324576698", "1324576701", "1324576705", "1324576710", "1324576714", "1324576720", "1324576724", "1324576729", "1324576734", "1324576740", "1324576743", "1324576747", "1324576752", "1324576757", "1324576763", "1324576767", "1324576770", "1324576775", "1324576779", "1324576782", "1324576790", "1324576794"}
	return
}

func (s *ChatServiceImpl) RecordMessage(ctx context.Context, memberId int64, message *zhihaitu_model.TableBmbConvMessage) error {
	account, err := s.openapiAccountDAO.GetByMemberId(ctx, memberId)
	if err != nil {
		return err
	}

	message.AccountID = account.ID
	_, err1 := s.bmbConvMessageDAO.CreateConvMessage(ctx, message)
	if err1 != nil {
		return err1.Error()
	}

	return nil
}

func (s *ChatServiceImpl) UpdateMessage(ctx context.Context, msgId string, updates map[string]interface{}) error {
	err := s.bmbConvMessageDAO.UpdateConvMessageByMsgID(ctx, msgId, updates)
	if err != nil {
		return err.Error()
	}

	return nil
}

func (s *ChatServiceImpl) GetMsgsByConvID(ctx context.Context, convId string, accountId int64) ([]*zhihaitu_model.TableBmbConvMessage, error) {
	conversion, err := s.bmbConversationDao.GetConversationByID(ctx, convId)
	if err != nil {
		if err.Code() == macro.SERVICE_CODE_CONVERSATION_NOT_FOUND.Code() {
			return []*zhihaitu_model.TableBmbConvMessage{}, nil
		} else {
			return nil, err.Error()
		}
	}

	if conversion.IsDeleted == zhihaitu_model.Deleted {
		return []*zhihaitu_model.TableBmbConvMessage{}, nil
	}

	messages, err := s.bmbConvMessageDAO.GetConvMessageByPage(ctx, convId, accountId, 0, 200)
	if err != nil {
		return nil, err.Error()
	}

	return messages, nil
}

func (s *ChatServiceImpl) CreateConversionIfNotExist(ctx context.Context, convId string, account *zhihaitu_model.TableOpenapiAccount, content string) error {
	_, err := s.bmbConversationDao.GetConversationByID(ctx, convId)
	if err == nil {
		return nil
	}

	if err.ServiceCode == macro.SERVICE_CODE_CONVERSATION_NOT_FOUND {
		conversation := &zhihaitu_model.TableBmbConversation{
			ConvID:     convId,
			CreateTime: time.Now(),
			UpdateTime: time.Now(),
			Title:      content[:zrecUtil.Min(20, len(content))],
			AccountID:  account.ID,
			AppID:      constant.ZhiHaiTuAppID,
		}
		err = s.bmbConversationDao.CreateConversion(ctx, conversation)
		if err != nil {
			return err.Error()
		}

		sessionCreated := &zhihaitu_model.SessionCreated{
			SessionID:  convId,
			UserID:     strconv.FormatInt(account.MemberID, 10),
			UpdateTime: time.Now().Format("20060102150405"),
		}
		log.Info(ctx, "send data. sessionCreated=", lo.Must(json.Marshal(sessionCreated)))
		zhihaitu_model.SendData(ctx, sessionCreated)
	} else {
		return err.Error()
	}

	return nil
}
