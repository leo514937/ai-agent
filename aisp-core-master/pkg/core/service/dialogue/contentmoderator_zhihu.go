package dialogue

// 内容安全侧对接人: 张津铭, 张宝哲
// 接口文档: https://wiki.in.zhihu.com/pages/viewpage.action?pageId=437722630

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/go/utils"
	protoRiskCheck "git.in.zhihu.com/one-rpc-go/thrift-eval-regulate-core/eval_regulate_core_thrift/risk_check"
	protoEvalRegulateCore "git.in.zhihu.com/thrift-go/eval_regulate_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/google/uuid"
	"github.com/samber/lo"
)

const (
	appID        = "1001"
	sceneGroupID = 90005
)

const (
	protoRoleUser    = "USER"
	protoRoleAI      = "SYSTEM"
	protoCodeSuccess = 200
	protoActionPass  = 200
)

const (
	userBlackListKey    = "user_blacklist"
	keywordBlackListKey = "keyword_blacklist"
)

var ErrCodeIsNotSuccess = fmt.Errorf("code is not success")

type ZhihuContentModerator struct {
	riskCheckService protoRiskCheck.RiskCheckService
	evalService      protoEvalRegulateCore.EvalService

	apolloClient config.Client
}

var _ ContentModerator = (*ZhihuContentModerator)(nil)

func NewZhihuContentModerator() *ZhihuContentModerator {
	riskCheckClient := tzone.NewClient("RiskCheckService", tzone.Timeout(3*time.Second), tzone.TargetName("eval-regulate-core-rpc"))
	evalClient := tzone.NewClient("EvalService", tzone.Timeout(3*time.Second), tzone.TargetName("eval-regulate-core-rpc"))

	return &ZhihuContentModerator{
		riskCheckService: protoRiskCheck.NewRiskCheckServiceClient(riskCheckClient),
		evalService:      protoEvalRegulateCore.NewEvalServiceClient(evalClient),

		apolloClient: config.GetClient(),
	}
}

func (m *ZhihuContentModerator) Review(ctx context.Context, request *ReviewRequest) (ReviewResult, string, error) {
	logger := log.WithField(ctx, "request", request)

	result, reason, err := m.checkLocalRules(ctx, request)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "check local rules failed")
		return result, reason, err
	}
	if result != ReviewResultPass {
		return result, reason, nil
	}

	result, reason, err = m.checkRemoteRules(ctx, request)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "check remote rules failed")
		return result, reason, err
	}
	return result, reason, nil
}

func (m *ZhihuContentModerator) checkRemoteRules(ctx context.Context, request *ReviewRequest) (ReviewResult, string, error) {
	logger := log.WithField(ctx, "request", request)

	if request.TenantID == macro.TenantIDCAS || request.TaskID == macro.TaskGenTitle {
		logger.Info(ctx, "use eval")
		return m.checkRemoteRulesByEval(ctx, request)
	}

	contents := lo.Flatten(lo.Map(request.History, func(entry *HistoryEntry, _ int) []*protoRiskCheck.CheckContentDetail {
		return []*protoRiskCheck.CheckContentDetail{
			{
				Role: protoRoleUser,
				// 因为 UserMessage 和 AIMessage 共用 DialogueID, 所以需要加上 MessageRole 来区分
				TextID:   m.generateMessageID(entry.DialogueID, model.MessageRoleUser),
				TextDesc: entry.UserMessage,
			},
			{
				Role:     protoRoleAI,
				TextID:   m.generateMessageID(entry.DialogueID, model.MessageRoleAI),
				TextDesc: entry.AIMessage,
			},
		}
	}))
	contents = append(contents, &protoRiskCheck.CheckContentDetail{
		Role:     protoRoleUser,
		TextID:   m.generateMessageID(request.DialogueID, model.MessageRoleUser),
		TextDesc: request.UserMessage,
	})
	if request.AIMessage != "" {
		contents = append(contents, &protoRiskCheck.CheckContentDetail{
			Role:     protoRoleAI,
			TextID:   m.generateMessageID(request.DialogueID, model.MessageRoleAI),
			TextDesc: request.AIMessage,
		})
	}

	param := &protoRiskCheck.RiskCheckParam{
		Headers: &protoRiskCheck.CheckHeader{}, // 不用该接口过反作弊, 所以不传用户指纹
		GlobalParams: &protoRiskCheck.CheckGlobalParam{
			AppID:        appID,
			SceneGroupID: sceneGroupID,
			Nonce:        lo.Must(uuid.NewRandom()).String(),
			Timestamp:    util.TimeUnixMilli(),
			// 内部 RPC, 不需要签名
			SignMethod: "",
			Sign:       "",
			Version:    "",
		},
		DetailParams: &protoRiskCheck.CheckContentParam{
			MemberID: lo.Must(utils.ParseInt64(request.UserID)),
			Content:  contents,
		},
	}

	logger = logger.WithField(ctx, "param", param)
	result, err := m.riskCheckService.RiskCheck(ctx, param)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "risk check failed")
		return "", "", err
	}

	logger = logger.WithField(ctx, "result", result)
	if result.Code != protoCodeSuccess {
		logger.Error(ctx, "risk check failed")
		return "", "", ErrCodeIsNotSuccess
	}

	if result.Data.GetAction() != protoActionPass {
		logger.Info(ctx, "risk check not pass")
		return ReviewResultNotPass, utils.MustMarshalToString(result.Data.HitInfos), nil
	}

	logger.Info(ctx, "risk check pass")
	return ReviewResultPass, "", nil
}

const (
	userMessageEvalSceneID = 10
	aiMessageEvalSceneID   = 11
	genTitleEvalSceneID    = 22
)

func (m *ZhihuContentModerator) checkRemoteRulesByEval(ctx context.Context, request *ReviewRequest) (ReviewResult, string, error) {
	logger := log.WithField(ctx, "request", request)

	paramSceneID := int64(0)
	paramRequest := make(map[string]any)
	if request.TenantID == macro.TenantIDCAS {
		if request.AIMessage == "" {
			paramSceneID = userMessageEvalSceneID
			paramRequest["content"] = request.UserMessage
			paramRequest["obj_id"] = utils.Int64ToStr(request.DialogueID << 1)
		} else {
			paramSceneID = aiMessageEvalSceneID
			paramRequest["content"] = request.AIMessage
			paramRequest["obj_id"] = utils.Int64ToStr(request.DialogueID<<1 + 1)
		}
	} else if request.TaskID == macro.TaskGenTitle {
		if request.AIMessage == "" {
			return ReviewResultPass, "", nil
		} else {
			paramSceneID = genTitleEvalSceneID
			paramRequest["content"] = request.AIMessage
		}
	}

	param := protoEvalRegulateCore.NewEvalParam()
	param.SceneID = lo.ToPtr[int64](paramSceneID)
	param.Request = lo.ToPtr(utils.MustMarshalToString(paramRequest))

	resp, err := m.evalService.Eval(ctx, param)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "eval failed")
		return "", "", err
	}
	if resp.IsHit {
		return ReviewResultNotPass, utils.MustMarshalToString(resp.HitRules), nil
	}
	return ReviewResultPass, "", nil
}

func (*ZhihuContentModerator) generateMessageID(dialogueID int64, role model.MessageRole) string {
	if dialogueID == 0 {
		return ""
	}
	return fmt.Sprintf("%d-%s", dialogueID, role)
}

func (m *ZhihuContentModerator) getConfigStrings(key string) []string {
	raw := m.apolloClient.GetString(key)
	if raw == "" {
		return nil
	}
	return strings.Split(raw, ",")
}

func (m *ZhihuContentModerator) checkLocalRules(ctx context.Context, request *ReviewRequest) (ReviewResult, string, error) {
	userIDs := m.getConfigStrings(userBlackListKey)
	if lo.Contains(userIDs, request.UserID) {
		return ReviewResultNotPass, "user in black list", nil
	}
	keywords := m.getConfigStrings(keywordBlackListKey)
	for _, keyword := range keywords {
		if strings.Contains(request.UserMessage, keyword) {
			return ReviewResultNotPass, fmt.Sprintf("user message contains keyword: %s", keyword), nil
		}
	}
	return ReviewResultPass, "", nil
}

func init() {
	DefaultContentModerator = NewZhihuContentModerator()
}
