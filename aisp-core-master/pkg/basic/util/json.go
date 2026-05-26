package util

import (
	"bytes"
	"encoding/json"
	"fmt"
	"reflect"
)

func JSONUnmarshal(data []byte, v interface{}) error {
	buffer := bytes.NewBuffer(data)
	decoder := json.NewDecoder(buffer)
	decoder.UseNumber()
	return decoder.Decode(&v)
}

// 获取 json 忽略错误，主要用于 pb 调试
func GetJSONIgnoreError(v interface{}) string {
	s, _ := json.Marshal(v)
	return string(s)
}

// JsonMarshalByIgnoreHTML 编译Json
func JsonMarshalByIgnoreHTML(v interface{}) ([]byte, error) {
	// 解决问题
	byteBuf := bytes.NewBuffer([]byte{})
	encoder := json.NewEncoder(byteBuf)
	encoder.SetEscapeHTML(false) // 不转义 特殊字符
	err := encoder.Encode(v)
	if err != nil {
		return []byte{}, err
	}
	return byteBuf.Bytes(), nil
}

func DeepCopyByJSON(dest interface{}, src interface{}) error {
	if src == nil {
		return nil
	}
	if reflect.TypeOf(dest) != reflect.TypeOf(src) {
		return fmt.Errorf("dest[%v] and src[%v] type is not equal", reflect.TypeOf(dest), reflect.TypeOf(src))
	}

	if reflect.ValueOf(dest).Kind() != reflect.Ptr || reflect.ValueOf(src).Kind() != reflect.Ptr {
		return fmt.Errorf("dest[%v] and src[%v] must be ptr", reflect.ValueOf(dest).Kind(), reflect.ValueOf(src).Kind())
	}
	str, err := json.Marshal(src)
	if err != nil {
		return err
	}
	return json.Unmarshal(str, dest)
}

func DeepCopyByJSONAndReturn(src interface{}) interface{} {
	if src == nil {
		return nil
	}

	dest := reflect.New(reflect.TypeOf(src).Elem()).Interface()

	str, err := json.Marshal(src)
	if err != nil {
		return nil
	}

	err = json.Unmarshal(str, dest)
	if err != nil {
		return nil
	}

	return dest
}
