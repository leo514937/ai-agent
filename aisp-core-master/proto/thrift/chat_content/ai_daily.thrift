namespace py chat_content_thrift.ai_daily
namespace go chat_content_thrift.ai_daily
namespace java com.zhihu.chat_content_thrift.ai_daily

include "common.thrift"

struct AiDailyRecommendRequest {
    1: required i64 user_id;       // 用户ID
    2: optional string date;       // 快照日期
    3: optional string token;      // 客态用户token
    4: optional string source;     // 请求来源
}

// 答案项
struct AnswerItem {
  1: required string doc_type;        // 文档类型
  2: required string author_name;     // 作者名称
  3: optional string author_url;      // 作者链接
  4: optional string author_hash_id;  // 作者哈希ID
  5: optional string detail;          // 详情
  6: optional string url;             // 链接
  7: optional string url_token;       // 链接token
}

// 问题项
struct QuestionItem {
  1: required string doc_type;      // 文档类型
  2: required string title;         // 标题
  3: optional string detail;        // 详情
  4: optional string url;           // 链接
  5: optional string url_token;     // 链接token
  6: optional list<AnswerItem> items;     // 内容摘要
}

//
struct QueryPlaylistResponse {
  1: required string title;               // 标题
  2: required string date;                // 日期
  3: required string share_token;         // 分享token
  4: required list<QuestionItem> contents;      // 内容列表
}

struct AiDailyRecommendResponse {
	1: required i64 code;
	2: required string message;
	3: required QueryPlaylistResponse playlist_data;
}

// =================================== service ===================================

service AiDailyRecommendService { // 今日精选
    AiDailyRecommendResponse AiDailyRecommend(1: AiDailyRecommendRequest req)
}