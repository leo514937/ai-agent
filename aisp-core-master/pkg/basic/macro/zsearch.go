package macro

import (
	"git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"github.com/spf13/cast"
)

var (
	ContentDocTypeArticle = cast.ToString(int64(search_service_thrift.Vertical_ARTICLE))
	ContentDocTypeAnswer  = cast.ToString(int64(search_service_thrift.Vertical_ANSWER))
	ContentDocTypeWeiPu   = cast.ToString(int64(search_service_thrift.Vertical_DomesticScholar))
	ContentDocTypeArxiv   = cast.ToString(int64(search_service_thrift.Vertical_ForeignScholar))
)

const (
	RestrictedSceneMember   string = "member"
	RestrictedFieldMemberId string = "member_id"
)
