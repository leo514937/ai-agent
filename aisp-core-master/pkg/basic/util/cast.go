package util

import (
	"strconv"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

func Int64ToStr(i int64) string {
	return strconv.FormatInt(i, 10)
}

func Float64String(f float64) string {
	return strconv.FormatFloat(f, 'f', -1, 64)
}

func Int32String(i int32) string {
	return Int64ToStr(int64(i))
}

func Int2String(i int) string {
	return Int64ToStr(int64(i))
}

func Bool2Int(b bool) int {
	if b {
		return 1
	}
	return 0
}

func Bool2String(b bool) string {
	if b {
		return "true"
	}
	return "false"
}

func String2Int64(s string) (i int64, err error) {
	return strconv.ParseInt(s, 10, 64)
}

func String2Float64(s string) (i float64, err error) {
	return strconv.ParseFloat(s, 64)
}

func SafeString2Int64(str string, safeVal int64) int64 {
	val, err := strconv.ParseInt(str, 10, 64)
	if err != nil {
		return safeVal
	}

	return val
}

func Int64String(i int64) string {
	return strconv.FormatInt(i, 10)
}

func Float64SliceToFloat32(in []float64) []float32 {
	rst := make([]float32, len(in))
	for index, item := range in {
		rst[index] = float32(item)
	}
	return rst
}

func Float64TwoDemensionalSliceToFloat32(in [][]float64) [][]float32 {
	rst := make([][]float32, len(in))
	for index, items := range in {
		rst[index] = Float64SliceToFloat32(items)
	}
	return rst
}

func StringSliceToFloat64(in []string) []float64 {
	rst := make([]float64, len(in))
	for index, item := range in {
		if val, err := strconv.ParseFloat(item, 64); err == nil {
			rst[index] = val
		}
	}
	return rst
}

func Int64SliceToString(in []int64) []string {
	rst := make([]string, len(in))
	for index, item := range in {
		rst[index] = strconv.FormatInt(item, 10)
	}
	return rst
}

func StringSliceToInt64(in []string) []int64 {
	rst := make([]int64, len(in))
	for index, item := range in {
		if val, err := strconv.ParseInt(item, 10, 64); err == nil {
			rst[index] = val
		}
	}
	return rst
}

func InterfaceTryGetInt64(v interface{}, defaultValue int64) int64 {
	var r = defaultValue
	switch value := v.(type) {
	case int:
		r = int64(value)
	case int32:
		r = int64(value)
	case int64:
		r = value
	case float32:
		r = int64(value)
	case float64:
		r = int64(value)
	case string:
		r64, err := String2Int64(value)
		if err == nil {
			r = r64
		}
	}
	return r
}

func InterfaceTryGetFloat64(v interface{}, defaultValue float64) float64 {
	var r = defaultValue
	switch value := v.(type) {
	case int:
		r = float64(value)
	case int32:
		r = float64(value)
	case int64:
		r = float64(value)
	case float32:
		r = float64(value)
	case float64:
		r = value
	case string:
		r64, err := String2Float64(value)
		if err == nil {
			r = r64
		}
	}
	return r
}

func InterfaceTryGetString(v interface{}, defaultValue string) string {
	var r = defaultValue
	switch value := v.(type) {
	case int:
		r = Int2String(value)
	case int32:
		r = Int2String(int(value))
	case int64:
		r = Int2String(int(value))
	case float32:
		r = Float64String(float64(value))
	case float64:
		r = Float64String(float64(value))
	case string:
		r = value
	}
	return r
}

func InterfaceTryGetStringSlice(v interface{}, defaultValue []string) []string {
	var r = defaultValue
	switch value := v.(type) {
	case []interface{}:
		r = make([]string, len(value))
		for index, item := range value {
			r[index] = InterfaceTryGetString(item, "")
		}
	}
	return r
}

var docTypeContentTypeMap = map[content.DocType_Type]proto.DocType{
	content.DocType_Answer:           proto.DocType_ANSWER,
	content.DocType_Article:          proto.DocType_ARTICLE,
	content.DocType_Knowledge:        proto.DocType_USER_KNOWLEDGE,
	content.DocType_UniversalOffSite: proto.DocType_UNIVERSAL_OFFSITE,
	content.DocType_Paper:            proto.DocType_PAPER,
	content.DocType_ZhiDaUserUpload:  proto.DocType_ZHI_DA_USER_UPLOAD,
	content.DocType_Webpage:          proto.DocType_EXTERNAL_WEBPAGE,
	content.DocType_InternalDoc:      proto.DocType_INTERNAL_DOC,
	content.DocType_AispUserUpload:   proto.DocType_AISP_USER_UPLOAD,
}

var contentTypeDocTypeMap map[proto.DocType]content.DocType_Type

func init() {
	contentTypeDocTypeMap = make(map[proto.DocType]content.DocType_Type)
	for key, value := range docTypeContentTypeMap {
		contentTypeDocTypeMap[value] = key
	}
}

func ContentType2DocType(contentType proto.DocType) content.DocType_Type {
	docType, isOK := contentTypeDocTypeMap[contentType]
	if !isOK {
		docType = content.DocType_Unknown
	}
	return docType
}

func DocType2ContentType(docType content.DocType_Type) proto.DocType {
	contentType, isOK := docTypeContentTypeMap[docType]
	if !isOK {
		contentType = proto.DocType_UNKNOWN_DOCTYPE
	}
	return contentType
}

func CastZeroFloat(x float64, defaultValue float64) float64 {
	if x == 0.0 {
		return defaultValue
	}
	return x
}
