namespace py chat_content_thrift.offline
namespace go chat_content_thrift.offline
namespace java com.zhihu.chat_content_thrift.offline

include "common.thrift"

struct SaveQuestionPhraseRequest {
	1: required list<string> questions; // 问题短语List 最好控制在500以内
}

struct SaveQuestionPhraseResponse {
	1: required i64 Code;       // 0-成功，非0-失败
	2: required string Message;
}

service OfflineService {
    SaveQuestionPhraseResponse SaveQuestionPhrase(1: SaveQuestionPhraseRequest req)
}