package util

import (
	"reflect"
	"time"

	"github.com/mitchellh/mapstructure"
)

// MapToStruct 通用函数，将 map[string]interface{} 转换为指定的结构体类型 T
func MapToStruct[T any](m map[string]interface{}) (*T, error) {
	var result T
	err := mapstructure.Decode(m, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

func DeepCopy(src interface{}) interface{} {
	if src == nil {
		return nil
	}

	// 获取源值的反射值
	srcValue := reflect.ValueOf(src)

	// 如果是指针，获取其指向的元素
	if srcValue.Kind() == reflect.Ptr {
		if srcValue.IsNil() {
			return nil
		}
		srcValue = srcValue.Elem()
	}

	// 根据类型进行不同的处理
	switch srcValue.Kind() {
	case reflect.Struct:
		// Special handling for time.Time
		if srcValue.Type() == reflect.TypeOf(time.Time{}) {
			return src
		}

		// 创建新的结构体指针
		dst := reflect.New(srcValue.Type())

		// 遍历结构体的所有字段
		for i := 0; i < srcValue.NumField(); i++ {
			field := srcValue.Field(i)
			if field.CanInterface() {
				// 跳过不可导出的字段
				fieldType := srcValue.Type().Field(i)
				if !fieldType.IsExported() {
					continue
				}

				// 递归深拷贝字段
				copiedValue := DeepCopy(field.Interface())
				if copiedValue != nil {
					dst.Elem().Field(i).Set(reflect.ValueOf(copiedValue))
				}
			}
		}
		return dst.Interface()

	case reflect.Ptr:
		// Special handling for *time.Time
		if srcValue.Type().Elem() == reflect.TypeOf(time.Time{}) {
			return srcValue.Interface()
		}

		// Handle other pointer types
		if srcValue.IsNil() {
			return nil
		}
		return DeepCopy(srcValue.Elem().Interface())

	case reflect.Slice:
		// 创建新的切片
		dst := reflect.MakeSlice(srcValue.Type(), srcValue.Len(), srcValue.Cap())

		// 递归深拷贝每个元素
		for i := 0; i < srcValue.Len(); i++ {
			dst.Index(i).Set(reflect.ValueOf(DeepCopy(srcValue.Index(i).Interface())))
		}
		return dst.Interface()

	case reflect.Map:
		// 创建新的map
		dst := reflect.MakeMap(srcValue.Type())

		// 递归深拷贝每个键值对
		for _, key := range srcValue.MapKeys() {
			value := srcValue.MapIndex(key)
			dst.SetMapIndex(reflect.ValueOf(DeepCopy(key.Interface())), reflect.ValueOf(DeepCopy(value.Interface())))
		}
		return dst.Interface()

	case reflect.Interface:
		// 如果接口不为空，递归深拷贝其实际值
		if !srcValue.IsNil() {
			return DeepCopy(srcValue.Elem().Interface())
		}
		return nil

	case reflect.Chan, reflect.Func, reflect.UnsafePointer:
		// 这些类型不支持深拷贝，返回原值
		return src

	default:
		// 对于基本类型（int, string等），直接返回原值
		return src
	}
}
