package model

import proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"

type Security struct {
	BusinessStage    proto.BusinessStage `json:"business_stage"`
	RedLine          string              `json:"red_line"`
	FAQ              string              `json:"faq"`
	KnowLedgeEnhance []string            `json:"know_ledge_enhance"`
	ReviewResult     *ReviewResult       `json:"review_result"`
}

func (s *Security) IsSecurityAllPassed() bool {
	isRedLinePassed := s.RedLine == ""
	isReviewPassed := s.ReviewResult == nil || s.ReviewResult.IsAvailable
	isFAQPassed := s.FAQ == ""
	// 红线必答通过，且安审接口通过，即为通过
	return isRedLinePassed && isReviewPassed && isFAQPassed
}

type ReviewResult struct {
	IsAvailable  bool   `json:"is_passed"`
	FailReason   string `json:"fail_reason"`
	RequestInfo  string `json:"request_info"`
	ResponseInfo string `json:"response_info"`
}

func (r *ReviewResult) GetIsAvailable() bool {
	if r != nil {
		return r.IsAvailable
	}
	return false
}

func (r *ReviewResult) GetFailReason() string {
	if r != nil {
		return r.FailReason
	}
	return ""
}
