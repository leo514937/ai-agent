namespace py chat_content_thrift.content
namespace go chat_content_thrift.content
namespace java com.zhihu.chat_content_thrift.content

include "common.thrift"


// =================================== enum ===================================

enum QuestionState {
    NORMAL = 1,      //  提问
    DISPOSED = 2     //  处置
}

enum QueryType {
    QUESTION = 1,    //  问题
    ANSWER = 2       //  回答
}

enum AnswerType {
    OTHER = 0,      //  其他
    RICH_TEXT = 1,  //  富文本
    PICTURE = 2,    // 图片
    AUDIO = 3,      // 音频
    VIDEO = 4,      // 视频
    FILE = 5        // 文件
}

enum SecurityMethod {
    NONE = 0,               // 无命中
    SECURITY_REFUSE = 1,    // 安全拦截
    RED_LINE = 2,           // 红线必答
    FAQ = 3                 // faq 问答库
}

// =================================== struct ===================================

struct DisposeConversationRequest {
	1: required string SessionID;
}

struct DisposeConversationResponse {
	1: required i64 Code;        // 0-成功，非0-失败
	2: required string Message;
}

struct QueryQuestionDetailRequest {
	1: required string QuestionID;
}

struct QuestionDetail {
	1: required string SessionID;
	2: required string QuestionID;
	3: required string MemberID;
  	4: required string PublishTime;
    5: required QuestionState State;
    6: required string Content;
}

struct QueryQuestionDetailResponse {
	1: required i64 Code;
	2: required string Message;
	3: required QuestionDetail Data;
}

struct QueryConversationDetailRequest {
	1: required string SessionID;
	2: required QueryType QueryType;
}

struct AnswerDetail {
	1: required string SessionID;
	2: required string QuestionID;
	3: required string AnswerID;
  	4: required string PublishTime;
    5: required AnswerType AnswerType;
}

struct ConversationDetail {
	1: optional list<QuestionDetail> Questions;
	2: optional list<AnswerDetail> Answers;
}

struct QueryConversationDetailResponse {
	1: required i64 Code;
	2: required string Message;
	3: required ConversationDetail Data;
}

struct GetWhiteListMemberIDsRequest {
}

struct GetWhiteListMemberIDsResponse {
	1: required i64 Code;       // 0-成功，非0-失败
	2: required string Message;
	3: required list<string> Data;
}


struct Content {
	1: required i64 DocId;        // 内容平台ID  如 3311332 （对应搜索接口的 OriginalID）
	2: required string DocType;   // 内容平台类型 如 ANSWER QUESTION
}

// 搜索结果通知 Request & Response
struct SearchResultNoticeRequest {
	1: required i64 MemberId;                       // 用户ID
	2: required string Query;                       // 用户原始Query
	3: required list<Content> RecallContentList;    // 召回内容列表
}
struct SearchResultNoticeResponse {
	1: required i64 Code;       // 0-成功，非0-失败
	2: required string Message;
}


struct KnowledgeBaseDocRetrieveRequest {
  1: required string query;
  2: required i32 top_k;
  3: required string doc_unique_id;
}

struct KnowledgeBaseDocRetrieveItem {
  1: required string text;
  2: required double similarity = 2;
}

struct KnowledgeBaseDocRetrieveResponse {
  1: required list<KnowledgeBaseDocRetrieveItem> items;
}

struct KnowledgeBaseDocDetailRequest {
  1: required string doc_unique_id;
}

struct KnowledgeBaseDocDetailResponse {
  1: required string text;
}

struct ChatRecordRequest {
    1: optional i64 member_id;              // 用户id
    2: optional string session_id;          // 会话id
    3: optional string query_id;            // 问题id
    4: optional string answer_id;           // 回答id
    5: optional string query;               // 问题
    6: optional string answer;              // 回答
    7: optional i64 request_time_start;     // 请求时间起，秒级时间戳
    8: optional i64 request_time_end;       // 请求时间止，秒级时间戳
    9: optional i64 response_time_start;    // 回答时间起，秒级时间戳
    10: optional i64 response_time_end;     // 回答时间止，秒级时间戳
    11: optional SecurityMethod security;   // 安全命中情况
}

struct ChatRecordQueryResponse {
    1: required i64 code;               // 0-成功，非0-失败
    2: required string message;         // 错误信息
    3: required list<ChatRecord> data;  // 日志列表
}

struct ChatRecord{
    1: required i64 member_id;              // 用户id
    2: required string session_id;          // 会话id
    3: required string query_id;            // 问题id
    4: required string answer_id;           // 回答id
    5: required string query;               // 问题
    6: required string answer;              // 回答
    7: required i64 request_time;           // 请求时间，秒级时间戳
    8: required i64 response_time;          // 回答时间，秒级时间戳
    9: required SecurityMethod security;    // 安全命中情况
}

// =================================== service ===================================

service ChatService {
	DisposeConversationResponse DisposeConversation(1: DisposeConversationRequest req)
	QueryQuestionDetailResponse QueryQuestionDetail(1: QueryQuestionDetailRequest req)
    QueryConversationDetailResponse QueryConversationDetail(1: QueryConversationDetailRequest req)
    GetWhiteListMemberIDsResponse GetWhiteListMemberIDs(1: GetWhiteListMemberIDsRequest req)
    // 搜索结果通知
    SearchResultNoticeResponse SearchResultNotice(1: SearchResultNoticeRequest req)
    KnowledgeBaseDocRetrieveResponse KnowledgeBaseDocRetrieve(1: KnowledgeBaseDocRetrieveRequest req)
    KnowledgeBaseDocDetailResponse KnowledgeBaseDocDetail(1: KnowledgeBaseDocDetailRequest req)
    // 给安全用于查询日志
    ChatRecordQueryResponse ChatRecordQuery(1: ChatRecordRequest req)
}