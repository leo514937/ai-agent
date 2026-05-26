package model

type RedisAnswerDetail struct {
	AnswerID           string `json:"answerId"`
	AnswerUrlToken     string `json:"answerUrlToken"`
	AnswerAuthorHashID string `json:"answerAuthorHashId"`
	AnswerUrl          string `json:"answerUrl"`
	AnswerSummary      string `json:"answerSummary"`
	AnswerAuthorUrl    string `json:"answerAuthorUrl"`
	AnswerAuthorName   string `json:"answerAuthorName"`
}

type RedisQuestionDetail struct {
	QuestionID       string               `json:"questionId"`
	QuestionUrlToken string               `json:"questionUrlToken"`
	QuestionUrl      string               `json:"questionUrl"`
	QuestionTitle    string               `json:"questionTitle"`
	QuestionDetail   string               `json:"questionDetail"`
	QuestionLikes    float64              `json:"questionLikes"`
	LabelContent     string               `json:"labelContent"`
	ConceptItem      string               `json:"conceptItem"`
	BayesItem        string               `json:"bayesItem"`
	KeyEntity        string               `json:"keyEntity"`
	Source           string               `json:"source"`
	Answers          []*RedisAnswerDetail `json:"answers"`
}
