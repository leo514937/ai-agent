package agent_tool

import (
	"encoding/json"
	"fmt"
	"reflect"
)

// ValidationResult 验证结果
type ValidationResult struct {
	Valid     bool     `json:"valid"`
	ToolName  string   `json:"tool_name"`
	Arguments string   `json:"arguments"`
	Errors    []string `json:"errors,omitempty"`
}

// ToolCallValidator 工具调用验证器
type ToolCallValidator struct {
	schemas map[string]map[string]interface{}
}

// NewToolCallValidator 创建验证器
func NewToolCallValidator() *ToolCallValidator {
	return &ToolCallValidator{
		schemas: make(map[string]map[string]interface{}),
	}
}

// RegisterTool 注册工具及其参数schema
func (v *ToolCallValidator) RegisterTool(toolName string, parameters map[string]interface{}) {
	v.schemas[toolName] = parameters
}

// ValidateToolCall 验证工具调用结果
func (v *ToolCallValidator) ValidateToolCall(toolName string, arguments string) ValidationResult {
	schema, exists := v.schemas[toolName]
	if !exists {
		return ValidationResult{
			Valid:     false,
			Errors:    []string{fmt.Sprintf("tool %s not registered", toolName)},
			ToolName:  toolName,
			Arguments: arguments,
		}
	}

	// 解析参数JSON
	var argumentsObj map[string]interface{}
	if err := json.Unmarshal([]byte(arguments), &argumentsObj); err != nil {
		return ValidationResult{
			Valid:     false,
			Errors:    []string{fmt.Sprintf("invalid JSON: %v", err)},
			ToolName:  toolName,
			Arguments: arguments,
		}
	}

	// 简化的参数验证
	validationResult := ValidationResult{
		Valid:     true,
		ToolName:  toolName,
		Arguments: arguments,
		Errors:    []string{},
	}

	// 验证必需字段
	if required, ok := schema["required"].([]interface{}); ok {
		for _, reqField := range required {
			fieldName := reqField.(string)
			if _, exists := argumentsObj[fieldName]; !exists {
				validationResult.Valid = false
				validationResult.Errors = append(validationResult.Errors,
					fmt.Sprintf("missing required field: %s", fieldName))
			}
		}
	}

	// 验证字段类型
	if properties, ok := schema["properties"].(map[string]interface{}); ok {
		for fieldName, fieldValue := range argumentsObj {
			if propSchema, exists := properties[fieldName]; exists {
				if propMap, ok := propSchema.(map[string]interface{}); ok {
					if expectedType, typeExists := propMap["type"]; typeExists {
						if !v.validateFieldType(fieldValue, expectedType.(string)) {
							validationResult.Valid = false
							validationResult.Errors = append(validationResult.Errors,
								fmt.Sprintf("field %s has invalid type, expected %s", fieldName, expectedType))
						}
					}
				}
			}
		}
	}

	return validationResult
}

// validateFieldType 验证字段类型
func (v *ToolCallValidator) validateFieldType(value interface{}, expectedType string) bool {
	switch expectedType {
	case "string":
		_, ok := value.(string)
		return ok
	case "number":
		_, ok := value.(float64)
		return ok
	case "integer":
		if f, ok := value.(float64); ok {
			return f == float64(int(f))
		}
		return false
	case "boolean":
		_, ok := value.(bool)
		return ok
	case "array":
		return reflect.TypeOf(value).Kind() == reflect.Slice
	case "object":
		_, ok := value.(map[string]interface{})
		return ok
	default:
		return true // 未知类型默认通过
	}
}

// String 返回验证结果的字符串表示
func (r *ValidationResult) String() string {
	if r.Valid {
		return fmt.Sprintf("✅ Tool '%s' validation passed", r.ToolName)
	}
	return fmt.Sprintf("❌ Tool '%s' validation failed: %v", r.ToolName, r.Errors)
}
