package impl

import (
	"context"
	"fmt"
	"time"

	"git.apache.org/thrift.git/lib/go/thrift"
	"git.in.zhihu.com/ecosystem-cd/evalsdk"
	evalsdkSchema "git.in.zhihu.com/ecosystem-cd/evalsdk/schema"
	baselog "git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-eval-regulate-core/eval_regulate_core_thrift/risk_check"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/google/uuid"
	"github.com/pkg/errors"
	"github.com/samber/lo"
)

var (
	_                       rpc.RiskCheckRPC = (*RiskCheckRPCImpl)(nil)
	DefaultRiskCheckRPCImpl rpc.RiskCheckRPC
)

func init() {
	DefaultRiskCheckRPCImpl = NewRiskCheckRPCImpl()
}

type RiskCheckRPCImpl struct {
	client *risk_check.RiskCheckServiceClient
}

func NewRiskCheckRPCImpl() *RiskCheckRPCImpl {
	return &RiskCheckRPCImpl{
		client: risk_check.NewRiskCheckServiceClient(
			tzone.NewClient("RiskCheckService",
				tzone.TargetName("eval-regulate-core-rpc"),
				tzone.Timeout(3*time.Second))),
	}
}

// RiskCheckInterestWord 发起 安全审核
func (r *RiskCheckRPCImpl) RiskCheckInterestWord(ctx context.Context, word string, source string) (*rpc.RiskCheckResp, error) {
	logger := log.WithField(ctx, "RiskCheckInterestWord", word)
	logger.Debug(ctx, "do RiskCheck Interest Word")
	flag, _, err := evalsdk.CallScene27(ctx, evalsdkSchema.Scene27Param{ContentText: word, Source: source})
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx,
			"invoke risk InterestWord(eval27) rpc error => flag:%v word:%v errorMsg:%v", flag, word, err)
		return &rpc.RiskCheckResp{Res: rpc.RiskCheckResUnPass, Action: -1}, err
	}

	var res rpc.RiskCheckRes
	if flag {
		logger.Warnf(ctx, "risk check InterestWord(eval27) res is unpass => word:%v", word)
		res = rpc.RiskCheckResUnPass
	} else {
		res = rpc.RiskCheckResPass
	}
	return &rpc.RiskCheckResp{Res: res}, nil
}

// RiskCheckRecallTitleAbstract 安全审核召回的标题摘要
func (r *RiskCheckRPCImpl) RiskCheckRecallTitleAbstract(ctx context.Context, dto rpc.RiskCheckRecallDto) (*rpc.RiskCheckResp, error) {
	text := fmt.Sprintf("%s,%s,%s", dto.Query, dto.Title, dto.Abstract)
	logger := log.WithField(ctx, "RiskCheckRecallTitleDesc", dto.Title)

	_, checkRes, err := evalsdk.CallScene270001(ctx, evalsdkSchema.Scene270001Param{
		BizSource:   fmt.Sprintf("%s.%s", dto.ClientSource, dto.TrafficSource),
		Source:      dto.Source,
		Url:         dto.Url,
		ContentText: text,
		FullContent: dto.FullContent,
		Query:       dto.Query,
		MemberID:    dto.MemberId,
		UserIp:      dto.UserIp,
		Extra: map[string]any{
			"member_id":     dto.MemberId,
			"session_id":    dto.SessionId,
			"question_id":   dto.QuestionId,
			"question_text": dto.QuestionText,
		},
	})

	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "RiskCheckRecallTitleDesc err. text:%s, err:%v", text, err)
		return &rpc.RiskCheckResp{Res: rpc.RiskCheckResUnPass, Action: -1}, err
	}

	var res rpc.RiskCheckRes
	if checkRes.IsHit {
		logger.Warnf(ctx, "risk check RecallTitleAbstract(eval270001) res is unpass => text:%v", text)
		res = rpc.RiskCheckResUnPass
	} else {
		res = rpc.RiskCheckResPass
	}
	return &rpc.RiskCheckResp{Res: res}, nil
}

// RiskCheckDeepSearch 安全审核 deepsearch 的 goal、queries、summary
func (r *RiskCheckRPCImpl) RiskCheckDeepSearch(ctx context.Context, dto rpc.RiskCheckDeepSearchDto) (*rpc.RiskCheckResp, error) {
	logger := log.WithField(ctx, "RiskCheckDeepSearch", util.GetJSONIgnoreError(dto))

	_, checkRes, err := evalsdk.CallScene690011(ctx, evalsdkSchema.Scene690011Param{
		QuestionID:    dto.QuestionId,
		MemberID:      dto.MemberId,
		SearchQuery:   dto.Goal,
		RecallSummary: dto.RecallSummary,
		SearchWord:    dto.SearchKeyWord,
	})

	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "RiskCheckDeepSearch err:%v", err)
		return &rpc.RiskCheckResp{Res: rpc.RiskCheckResUnPass, Action: -1}, err
	}

	var res rpc.RiskCheckRes
	if checkRes.HitCode == "501" || checkRes.HitCode == "502" {
		logger.Warnf(ctx, "risk check RiskCheckDeepSearch res is unpass")
		res = rpc.RiskCheckResUnPass
	} else {
		res = rpc.RiskCheckResPass
	}
	return &rpc.RiskCheckResp{Res: res}, nil
}

// RiskCheckDialog 发起 安全审核
func (r *RiskCheckRPCImpl) RiskCheckDialog(
	ctx context.Context, params *rpc.RiskCheckParams) (*rpc.RiskCheckResp, error) {
	logger := log.WithField(ctx, "doRiskCheckResult", params)
	if params.Contents == nil || len(params.Contents) == 0 {
		err := errors.Errorf("there is no detection content => %v", params)
		logger.Error(ctx, err)
		// 极端情况 无检测内容
		return &rpc.RiskCheckResp{Res: rpc.RiskCheckResUnPass, Action: -1}, err
	}

	// 判断 QueryExtra AnswerExtra 是否只有一个是不为空的情况
	// 如果都不为空 则认为业务调用法判断发生了异常 安全不予通过 需要业务方自行排查代码
	if params.QueryExtra != nil && params.AnswerExtra != nil {
		err := errors.Errorf("only one of QueryExtra and AnswerExtra can be null at a time => %v", params)
		logger.Error(ctx, err)
	}

	// 参数详情
	detailParams := &risk_check.CheckContentParam{
		MemberID: params.MemberId,
		Content:  params.Contents,
	}

	// 处理 QueryExtra 与 AnswerExtra
	if params.QueryExtra != nil {
		detailParams.QuestionInfo = params.QueryExtra
	}
	if params.AnswerExtra != nil {
		detailParams.AnswerInfo = params.AnswerExtra
	}

	header := &risk_check.CheckHeader{}
	if params.IP != "" {
		header.IP = &params.IP
	}
	if params.UserAgent != "" {
		header.UserAgent = &params.UserAgent
	}

	bizSource := fmt.Sprintf("%s.%s", params.ClientSource, params.TrafficSource)
	if params.DataSourceType != "" {
		bizSource += fmt.Sprintf(".%s", params.DataSourceType)
	}
	param := &risk_check.RiskCheckParam{
		Headers: header,
		GlobalParams: &risk_check.CheckGlobalParam{
			BizSource:    thrift.StringPtr(bizSource),
			ChatStyle:    thrift.StringPtr(params.ChatModel),
			AppID:        rpc.RiskCheckAppID,
			SceneGroupID: params.SourceId.ToConvert(),
			Source:       thrift.StringPtr(params.Scene),
			Nonce:        lo.Must(uuid.NewRandom()).String(),
			Timestamp:    util.TimeUnixMilli(),
			// 内部 RPC, 不需要签名
			SignMethod: "",
			Sign:       "",
			Version:    "",
		},
		DetailParams: detailParams,
	}

	var result *risk_check.RiskCheckResult_
	var err error
	runFunc := func(ctx context.Context) error {
		resultTmp, errTmp := r.client.RiskCheck(ctx, param)
		if log.GetLevel() == baselog.DebugLevel {
			logger.Debug(ctx, "rickCheck params: ", util.GetJSONIgnoreError(param))
		}
		if err != nil {
			err = errTmp
			return err
		}
		result = resultTmp
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	if err != nil || result == nil {
		logger.WithError(ctx, err).Errorf(ctx, "invoke risk check rpc error => params:%v errorMsg:%v", params, err)
		return &rpc.RiskCheckResp{Res: rpc.RiskCheckResUnPass, Action: -1}, err
	}

	logger = logger.WithField(ctx, "result", result)
	if result.Code != rpc.RiskCheckSuccessCode {
		tErr := errors.Errorf("risk check service failed => code:%v message:%v params:%v", result.Code, result.Message, params)
		logger.WithError(ctx, tErr).Error(ctx, tErr)
		return &rpc.RiskCheckResp{Res: rpc.RiskCheckResUnPass, Action: -1}, err
	}

	action := result.GetData().Action
	if action != rpc.RiskCheckSuccessCode {
		logger.Warnf(ctx, "risk check res is unpass => action:%v params:%v", action, params)
		return &rpc.RiskCheckResp{Res: rpc.RiskCheckResUnPass, Action: action}, nil
	}
	return &rpc.RiskCheckResp{Res: rpc.RiskCheckResPass, Action: action}, nil
}
