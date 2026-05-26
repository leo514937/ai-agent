package constants

import (
	"fmt"
	"math/rand"

	"github.com/pkg/errors"
)

// Greetings 问候
var Greetings = [...]string{
	"您好",
	"你好",
	"嗨",
	"Hello",
	"Hi",
	"早安",
	"午安",
	"晚安",
	"在么",
	"你是谁",
	"你叫什么名字",
	"你的名字是什么",
	"自我介绍",
	"介绍下你自己",
}

const (
	// GreetingAnswerFmt 问候回答格式
	GreetingAnswerFmt string = "您好，我是%s，很高兴为您服务！请问有什么可以帮到您。"
	// OutOfDomainAnswer 超出领域外回答格式
	OutOfDomainAnswerFmt string = "您好，我是%s，很高兴为您服务！您提的这个问题，已超出我的领域范畴，以下是我擅长的领域：\n%s，\n请换一个相关的问题试试吧"
	// AuthorPrompt 格式
	AuthorPromptFmt string = "现在你是一名%s行业的专家，你需要结合[上下文]，对用户的[问题]进行分析，根据用户的情况给出合理的答复。上下文:%s\n问题:%s"
	// QuestionPrompt 格式
	QuestionPromptFmt string = "现在你是一名%s行业的专家，你需要根据用户的[问题]和[上下文]返回一个和用户自身相关的的反问。上下文:%s\n问题:%s"
	// ConfigPath 配置文件地址
	ConfigPath string = "/user/tc_ai/data/digital_user/config/digital_user.jsonl"
)

// GetRandomGreeting 获取随机问候
func GetRandomGreeting() string {
	// 使用 rand.Intn 获取一个随机索引
	randomIndex := rand.Intn(len(Greetings))
	return Greetings[randomIndex]
}

// FmtStr 格式化字符串
func FmtStr(format string, args ...any) (str string, ex error) {
	defer func() {
		if r := recover(); r != nil {
			str = ""
			ex = errors.Errorf("Digital 格式化异常 => %s", r)
		}
	}()
	return fmt.Sprintf(format, args...), nil
}
