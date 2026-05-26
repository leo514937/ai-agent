package util

import (
	"context"
	"reflect"
	"strings"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_biz_ext/paper_biz_ext"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

const separator = ","

func JoinNamesToString(names ...string) string {
	if names == nil || len(names) == 0 {
		return ""
	}
	return strings.Join(names, separator)
}

func SplitNamesStringToArray(namesStr string) []string {
	if namesStr == "" {
		return []string{}
	}
	return strings.Split(namesStr, separator)
}

func GetFieldValue(logCtx context.Context, reqCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], fieldName string) (interface{}, reflect.Kind, bool) {
	stringValue, ok := reqCtx.DataMap().GetString(logCtx, fieldName)

	if ok {
		return stringValue, reflect.String, ok
	}

	boolValue, ok := reqCtx.DataMap().GetBool(logCtx, fieldName)
	if ok {
		return boolValue, reflect.Bool, ok
	}

	intValue, ok := reqCtx.DataMap().GetInt(logCtx, fieldName)
	if ok {
		return intValue, reflect.Int, ok
	}

	int8Value, ok := reqCtx.DataMap().GetInt8(logCtx, fieldName)
	if ok {
		return int8Value, reflect.Int8, ok
	}

	int16Value, ok := reqCtx.DataMap().GetInt16(logCtx, fieldName)
	if ok {
		return int16Value, reflect.Int16, ok
	}

	int32Value, ok := reqCtx.DataMap().GetInt32(logCtx, fieldName)
	if ok {
		return int32Value, reflect.Int32, ok
	}

	int64Value, ok := reqCtx.DataMap().GetInt64(logCtx, fieldName)
	if ok {
		return int64Value, reflect.Int64, ok
	}

	float64Value, ok := reqCtx.DataMap().GetFloat64(logCtx, fieldName)
	if ok {
		return float64Value, reflect.Float64, ok
	}

	float32Value, ok := reqCtx.DataMap().GetFloat32(logCtx, fieldName)
	if ok {
		return float32Value, reflect.Float32, ok
	}

	uintValue, ok := reqCtx.DataMap().GetUint(logCtx, fieldName)
	if ok {
		return uintValue, reflect.Uint, ok
	}

	uint8Value, ok := reqCtx.DataMap().GetUint8(logCtx, fieldName)
	if ok {
		return uint8Value, reflect.Uint8, ok
	}

	uint16Value, ok := reqCtx.DataMap().GetUint16(logCtx, fieldName)
	if ok {
		return uint16Value, reflect.Uint16, ok
	}

	uint32Value, ok := reqCtx.DataMap().GetUint32(logCtx, fieldName)
	if ok {
		return uint32Value, reflect.Uint32, ok
	}

	uint64Value, ok := reqCtx.DataMap().GetUint64(logCtx, fieldName)
	if ok {
		return uint64Value, reflect.Uint64, ok
	}

	return nil, reflect.Invalid, false
}

// GetFilterIncludeTypeConfig 获取过滤 白名单类型
func GetFilterIncludeTypeConfig(logicName string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]aiContent.DocType_Type, []paper_biz_ext.PaperPublishSource) {
	filterLogicConfByIncludeDocTypeStrArr := strings.Split(requestCtx.GetBizContext().GetLogicConfig(logicName, conf.FilterLogicConfByIncludeDocTypeArr), ",")
	filterIncludeDocTypeArr := make([]aiContent.DocType_Type, 0)
	for _, docTypeStr := range filterLogicConfByIncludeDocTypeStrArr {
		docType := aiContent.DocType_Type(aiContent.DocType_Type_value[docTypeStr])
		if docType == aiContent.DocType_Unknown {
			continue
		}
		filterIncludeDocTypeArr = append(filterIncludeDocTypeArr, docType)
	}

	filterLogicConfByIncludePaperArr := strings.Split(requestCtx.GetBizContext().GetLogicConfig(logicName, conf.FilterLogicConfByIncludePaperArr), ",")
	filterIncludePaperArr := make([]paper_biz_ext.PaperPublishSource, 0)
	for _, paperPublishSourceStr := range filterLogicConfByIncludePaperArr {
		paperPublishSourceFromString, paperPublishSourceFromStringErr := paper_biz_ext.PaperPublishSourceFromString(paperPublishSourceStr)
		if paperPublishSourceFromStringErr != nil {
			continue
		}
		filterIncludePaperArr = append(filterIncludePaperArr, paperPublishSourceFromString)
	}
	return filterIncludeDocTypeArr, filterIncludePaperArr
}
