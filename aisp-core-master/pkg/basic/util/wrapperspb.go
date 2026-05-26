package util

import "google.golang.org/protobuf/types/known/wrapperspb"

// Float32ToWrapperspbFloat 将 *float32 转换为 wrapperspb.FloatValue
func Float32ToWrapperspbFloat(f *float32) *wrapperspb.FloatValue {
	if f != nil {
		return wrapperspb.Float(*f)
	}
	return nil
}

// WrapperspbFloatToFloat32 将 wrapperspb.FloatValue 转换为 *float32
func WrapperspbFloatToFloat32(w *wrapperspb.FloatValue) *float32 {
	if w != nil {
		return &w.Value
	}
	return nil
}

// Int32ToWrapperspbInt32 将 *int32 转换为 wrapperspb.Int32Value
func Int32ToWrapperspbInt32(i *int32) *wrapperspb.Int32Value {
	if i != nil {
		return wrapperspb.Int32(*i)
	}
	return nil
}

// WrapperspbInt32ToInt32 将 wrapperspb.Int32Value 转换为 *int32
func WrapperspbInt32ToInt32(w *wrapperspb.Int32Value) *int32 {
	if w != nil {
		return &w.Value
	}
	return nil
}
