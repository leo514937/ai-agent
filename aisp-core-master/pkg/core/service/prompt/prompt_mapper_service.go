package prompt

import (
	"bytes"
	"context"
	"fmt"
	"reflect"
	"strings"
	"text/template"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/pkg/errors"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

const (
	ConfigNamespaceAI         = "ai.properties"
	ConfigNamespaceAITest     = "ai_test.properties"
	ConfigNamespaceZplus      = "zplus.properties"
	ConfigNamespaceInternalQa = "zhihu.internal-qa-prompts.properties"
)

func init() {
	ctx := context.Background()
	log.Infof(ctx, "PromptMapperService init.")
	config.SubscribeToNamespaces(ctx, ConfigNamespaceAI)
	config.SubscribeToNamespaces(ctx, ConfigNamespaceAITest)
	config.SubscribeToNamespaces(ctx, ConfigNamespaceZplus)
	config.SubscribeToNamespaces(ctx, ConfigNamespaceInternalQa)
	DefaultPromptMapperService = NewPromptMapperService()
	defaultPromptCache = cache.NewSafeCache(&cache.SafeCacheConfig{
		DefCacheTimeOut: 600,
	})
}

type PromptMapperService interface {
	// GetPromptTemplate 获取 prompt 模版
	GetPromptTemplate(ctx context.Context, code string) (string, bool)
	// FormatPromptById 获取 Prompt 模版 并完成Format工作
	FormatPromptById(ctx context.Context, code string, args any) (string, error)

	// TODO Update Delete 方法 需要删除Redis缓存（缓存一致性双删）

	// LoadPromptByApollo 从apollo 中加载 prompt
	LoadPromptByApollo(ctx context.Context, promptId string, defaultPromptTemp string, promptTag string, memberID int64) string
	LoadPromptByApolloNamespace(ctx context.Context, promptId string, defaultPromptTemp string, promptTag string, memberID int64, namespace string) string

	// BuildPromptWithApollo 从 apollo 中读取 prompt 模板并进行模板替换
	BuildPromptWithApollo(ctx context.Context, promptKey string, defaultPromptTemp string, promptTag string, memberID int64, promptInput interface{}) (string, error)
}

type PromptMapperServiceImpl struct {
	dao         dao.PromptMapperDAO
	redisClient redis.Client
}

var (
	_                          PromptMapperService = (*PromptMapperServiceImpl)(nil)
	DefaultPromptMapperService PromptMapperService
	cacheKeyPrefix             = "prompt:"
	defaultPromptCache         *cache.SafeCache
)

func NewPromptMapperService() *PromptMapperServiceImpl {
	return &PromptMapperServiceImpl{
		dao:         daoImpl.DefaultPromptMapperDAO,
		redisClient: resource.RedisByPrompt,
	}
}

func (s *PromptMapperServiceImpl) LoadPromptByApolloNamespace(ctx context.Context, promptId string, defaultPromptTemp string, promptTag string, memberID int64, namespace string) string {
	promptTemp := defaultPromptTemp
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "LoadPromptByApollo",
	})
	logger.Infof(ctx, "loadPrompt start.")

	if promptId == "" {
		logger.Infof(ctx, "loadPrompt promptID is empty.")
		return promptTemp
	}

	if memberID != 0 {
		userPrompt := config.GetStringByNamespace(ConfigNamespaceAITest, fmt.Sprintf("prompt.%s.%s", promptId, cast.ToString(memberID)), "")
		if userPrompt != "" {
			logger.Infof(ctx, "loadPrompt userPrompt ok. userPrompt: %s", userPrompt)
			return userPrompt
		}
	}

	if promptTag != "" {
		tagPrompt := config.GetStringByNamespace(namespace, fmt.Sprintf("prompt.%s.%s", promptId, promptTag), "")
		if tagPrompt != "" {
			logger.Infof(ctx, "loadPrompt defaultPrompt ok. defaultPrompt: %s", tagPrompt)
			return tagPrompt
		}
	}

	defaultPrompt := config.GetStringByNamespace(namespace, fmt.Sprintf("prompt.%s.default", promptId), "")
	if defaultPrompt != "" {
		logger.Infof(ctx, "loadPrompt defaultPrompt ok. defaultPrompt: %s", defaultPrompt)
		return defaultPrompt
	}

	logger.Infof(ctx, "loadPrompt prompt is empty. b.prompt: %s", promptTemp)
	return promptTemp
}

func (s *PromptMapperServiceImpl) LoadPromptByApollo(ctx context.Context, promptId string, defaultPromptTemp string, promptTag string, memberID int64) string {
	return s.LoadPromptByApolloNamespace(ctx, promptId, defaultPromptTemp, promptTag, memberID, ConfigNamespaceAI)
}

// GetPromptTemplate 获取 Prompt 模版
func (s *PromptMapperServiceImpl) GetPromptTemplate(ctx context.Context, code string) (string, bool) {
	// 获取 Prompt 模版 ， 并加入 Redis 安全缓存
	getCache, ok := defaultPromptCache.GetCache(ctx, cacheKeyPrefix+code,
		func(ctx context.Context, key string) (string, error) {
			entity, err := s.dao.GetByCode(ctx, code)
			if err != nil {
				return "", err
			}
			return entity.Prompt, nil
		})
	return getCache, ok
}

// FormatPromptById 格式化 Prompt 模版
func (s *PromptMapperServiceImpl) FormatPromptById(ctx context.Context, code string, args any) (string, error) {
	// 获取 Prompt 模版 ， 并加入 Redis 安全缓存
	getCache, ok := s.GetPromptTemplate(ctx, code)

	// 如果 ok 则需要 处理模版
	if ok {
		// 创建一个模板对象并解析模板字符串
		tmpl, err := template.New(code).Parse(getCache)
		if err != nil {
			return "", err
		}
		promptBuffer := &bytes.Buffer{}
		err = tmpl.Execute(promptBuffer, args)
		if err != nil {
			return "", err
		}

		return promptBuffer.String(), nil
	}
	return "", errors.Errorf("获取 Prompt 模版失败 => %s", code)
}

// BuildPromptWithApollo，输入 promptInput 可以是任何结构体
func (s *PromptMapperServiceImpl) BuildPromptWithApollo(ctx context.Context, promptKey string, defaultPromptTemp string, promptTag string, memberID int64, promptInput interface{}) (string, error) {
	promptTemp := s.LoadPromptByApollo(ctx, promptKey, defaultPromptTemp, promptTag, memberID)

	// 创建合并了日期字段的 map
	mergedData := s.mergeWithDateFields(promptInput)

	// 定义模板函数
	funcMap := template.FuncMap{
		"add": func(a, b int) int {
			return a + b
		},
		"sub": func(a, b int) int {
			return a - b
		},
		"eq": func(a, b int) bool {
			return a == b
		},
		"ne": func(a, b int) bool {
			return a != b
		},
		"lt": func(a, b int) bool {
			return a < b
		},
		"gt": func(a, b int) bool {
			return a > b
		},
		"last": func(i int, slice interface{}) bool {
			if slice == nil {
				return false
			}

			val := reflect.ValueOf(slice)
			if val.Kind() == reflect.Slice || val.Kind() == reflect.Array {
				return i == val.Len()-1
			}

			return false
		},
		"slice": func(slice interface{}, start, end int) interface{} {
			if slice == nil {
				return slice
			}

			val := reflect.ValueOf(slice)
			if val.Kind() == reflect.Slice || val.Kind() == reflect.Array {
				length := val.Len()

				// 边界检查
				if start < 0 {
					start = 0
				}
				if end > length {
					end = length
				}
				if start >= end {
					// 返回空切片，保持原类型
					return reflect.MakeSlice(val.Type(), 0, 0).Interface()
				}

				return val.Slice(start, end).Interface()
			}

			return slice
		},
		"len": func(slice interface{}) int {
			if slice == nil {
				return 0
			}

			// 使用反射处理所有类型
			val := reflect.ValueOf(slice)
			if val.Kind() == reflect.Slice || val.Kind() == reflect.Array {
				return val.Len()
			}

			return 0
		},
		"unicodeLen": func(str string) int {
			var r = []rune(str)
			return len(r)
		},
		"unicodeSubstr": func(str string, start, length int) string {
			return string(lo.Slice([]rune(str), start, start+length))
		},
		// 新增字符串比较函数
		"eqStr": func(a, b string) bool {
			return a == b
		},
		"neStr": func(a, b string) bool {
			return a != b
		},
	}

	promptTemplate, err := template.New(promptKey).Funcs(funcMap).Parse(promptTemp)
	if err != nil {
		return "", err
	}

	var promptBuffer strings.Builder
	err = promptTemplate.Execute(&promptBuffer, mergedData)
	if err != nil {
		return "", err
	}
	promptContent := promptBuffer.String()

	return promptContent, nil
}

// mergeWithDateFields 将原始数据与日期字段合并到同一级别
func (s *PromptMapperServiceImpl) mergeWithDateFields(promptInput interface{}) map[string]interface{} {
	result := make(map[string]interface{})

	// 添加日期字段
	result["Date"] = util.GetNowDate()
	result["Weekday"] = util.GetNowWeek()
	result["Time"] = util.GetNowTime()
	result["Yesterday"] = util.PlusDate(-1)
	result["Tomorrow"] = util.PlusDate(1)
	result["OneWeekDay"] = util.PlusDate(7)
	result["YesterdayWeekday"] = util.GetWeekDay(-1)
	result["TommorrowWeekday"] = util.GetWeekDay(1)
	result["Year"] = util.GetNowYear()
	result["LastYear"] = util.PlusYear(-1)
	result["NextYear"] = util.PlusYear(1)

	// 如果 promptInput 为 nil，直接返回日期字段
	if promptInput == nil {
		return result
	}

	// 使用反射获取原始数据的字段
	val := reflect.ValueOf(promptInput)

	// 如果是指针，获取指向的值
	if val.Kind() == reflect.Ptr {
		if val.IsNil() {
			return result
		}
		val = val.Elem()
	}

	// 如果是结构体，遍历其字段
	if val.Kind() == reflect.Struct {
		for i := 0; i < val.NumField(); i++ {
			field := val.Field(i)
			fieldType := val.Type().Field(i)

			// 获取字段名
			fieldName := fieldType.Name

			// 如果字段是可导出的，添加到结果中
			if field.CanInterface() {
				result[fieldName] = field.Interface()
			}
		}
	} else if val.Kind() == reflect.Map {
		// 如果是 map，直接合并
		for _, key := range val.MapKeys() {
			if key.Kind() == reflect.String {
				result[key.String()] = val.MapIndex(key).Interface()
			}
		}
	}

	return result
}
