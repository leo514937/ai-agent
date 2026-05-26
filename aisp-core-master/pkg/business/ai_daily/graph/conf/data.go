package conf

const (
	QuestionNum1PerTheme = 1 // 每个兴趣下取1个question
	QuestionNum2PerTheme = 2 // 每个兴趣下取2个question
	QuestionNum3PerTheme = 3 // 每个兴趣下取3个question
)

const (
	BayesLimit     = 2 // 最后的问题中每个贝叶斯领域数量限制
	EntityLimit    = 1 // 最后的问题中每个实体词数量限制
	HighLabelLimit = 2 // 每个高维标签词最多问题数
)

const (
	MaxThemeLimit           = 30 // 头部兴趣数
	MinThemeCountRandom     = 10 // 随机打散兴趣的最低兴趣数
	BatchSelectCountDefault = 3  // 随机挑选theme的batch数默认值

	ThemeCountLimit5  = 5  // 兴趣数量<= 5
	ThemeCountLimit10 = 10 // 兴趣数量<= 10
)

const (
	DataTotalQuestion = 10 // 返回的问题总数
)

const (
	ThemeSimilarThreshold    = 0.5 // 兴趣相似度分数阈值
	QuestionSimilarThreshold = 0.6 // 问题相似度分数阈值
)

const (
	DataSourceHighLabel = "high_label" // 高维标签召回
	DataSourceTheme     = "theme"      // theme召回
	DataSourceOther     = "other"      //兜底召回
)

const (
	SecurityRegulateQuestionPrefix = "ques_"
	SecurityRegulateAnswerPrefix   = "ans_"
)
