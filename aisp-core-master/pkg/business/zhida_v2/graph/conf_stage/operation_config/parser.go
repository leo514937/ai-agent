package operation_config

import (
	"encoding/json"
	"fmt"
	"reflect"
	"sync"
)

// CachedParser 带缓存的高性能JSON解析器
type CachedParser struct {
	typeMap        map[MessageType]reflect.Type
	instanceCache  map[MessageType]func() Message                // 缓存实例创建函数
	unmarshalCache map[MessageType]func([]byte) (Message, error) // 缓存反序列化函数
	mu             sync.RWMutex
}

// NewCachedParser 创建带缓存的解析器
func NewCachedParser() *CachedParser {
	parser := &CachedParser{
		typeMap:        make(map[MessageType]reflect.Type),
		instanceCache:  make(map[MessageType]func() Message),
		unmarshalCache: make(map[MessageType]func([]byte) (Message, error)),
	}

	// 自动注册并预热缓存
	parser.autoRegisterWithCache()
	return parser
}

// autoRegisterWithCache 自动注册并预热缓存
func (p *CachedParser) autoRegisterWithCache() {
	// 定义所有消息类型的构造函数
	constructors := []func() Message{
		func() Message {
			msg := &PromptMessage{}
			msg.Type = MessageTypePrompt
			return msg
		},
		// TODO 添加新类型时，只需在这里添加一行
	}

	for _, constructor := range constructors {
		instance := constructor()
		msgType := instance.GetType()
		t := reflect.TypeOf(instance).Elem()

		// 注册类型映射
		p.typeMap[msgType] = t

		// 缓存实例创建函数（避免每次反射）
		p.instanceCache[msgType] = constructor

		// 预热反序列化函数缓存
		p.preWarmUnmarshalCache(msgType, t)
	}
}

// preWarmUnmarshalCache 预热反序列化缓存
func (p *CachedParser) preWarmUnmarshalCache(msgType MessageType, t reflect.Type) {
	// 创建优化的反序列化函数
	p.unmarshalCache[msgType] = func(data []byte) (Message, error) {
		// 使用缓存的实例创建函数，避免反射
		instance := p.instanceCache[msgType]()

		// 直接反序列化到具体类型，避免interface{}转换
		if err := json.Unmarshal(data, instance); err != nil {
			return nil, fmt.Errorf("解析%s消息失败: %w", msgType, err)
		}

		return instance, nil
	}
}

// ParseMessage 高性能解析 - 使用缓存避免反射开销
func (p *CachedParser) ParseMessage(jsonStr string) (Message, error) {
	data := []byte(jsonStr)

	// 解析基础结构获取类型
	var baseMsg BaseMessage
	if err := json.Unmarshal(data, &baseMsg); err != nil {
		return nil, fmt.Errorf("解析基础消息失败: %w", err)
	}

	// 使用读锁获取缓存的反序列化函数
	p.mu.RLock()
	unmarshalFunc, exists := p.unmarshalCache[baseMsg.Type]
	p.mu.RUnlock()

	if !exists {
		return nil, fmt.Errorf("不支持的消息类型: %s (支持的类型: %v)", baseMsg.Type, p.GetSupportedTypes())
	}

	// 使用缓存的反序列化函数，避免反射开销
	return unmarshalFunc(data)
}

// GetSupportedTypes 获取支持的类型列表
func (p *CachedParser) GetSupportedTypes() []MessageType {
	p.mu.RLock()
	defer p.mu.RUnlock()

	types := make([]MessageType, 0, len(p.typeMap))
	for msgType := range p.typeMap {
		types = append(types, msgType)
	}
	return types
}

// ToJSON 将消息转换为JSON字符串
func (p *CachedParser) ToJSON(msg Message) (string, error) {
	jsonBytes, err := json.Marshal(msg)
	if err != nil {
		return "", fmt.Errorf("序列化消息失败: %w", err)
	}
	return string(jsonBytes), nil
}

// AddMessageType 动态添加新的消息类型（线程安全）
func (p *CachedParser) AddMessageType(constructor func() Message) {
	instance := constructor()
	msgType := instance.GetType()
	t := reflect.TypeOf(instance).Elem()

	p.mu.Lock()
	defer p.mu.Unlock()

	// 注册类型映射
	p.typeMap[msgType] = t

	// 缓存实例创建函数
	p.instanceCache[msgType] = constructor

	// 预热反序列化函数缓存
	p.preWarmUnmarshalCache(msgType, t)
}

// GetCacheStats 获取缓存统计信息
func (p *CachedParser) GetCacheStats() map[string]int {
	p.mu.RLock()
	defer p.mu.RUnlock()

	return map[string]int{
		"registered_types":    len(p.typeMap),
		"cached_constructors": len(p.instanceCache),
		"cached_unmarshalers": len(p.unmarshalCache),
	}
}
