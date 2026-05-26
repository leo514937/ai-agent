package gladiator

import (
	"context"
	"regexp"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/errors"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/samber/lo"
)

var variablePattern = regexp.MustCompile(`{{\s*([^}]+?)\s*}}`)

type Service interface {
	Play(ctx context.Context, gladiator *domainModel.Gladiator, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonResult, error)
}

type Impl struct {
	modelDAO        dao.ModelDAO
	modelGatewayRPC modelapi.ModelTarget
}

var (
	_              Service = (*Impl)(nil)
	DefaultService Service = NewService()
)

func NewService() *Impl {
	return &Impl{
		modelDAO:        dao.DefaultModelDAO,
		modelGatewayRPC: rpc.DefaultModelGatewayRouter,
	}
}

func (i *Impl) Play(ctx context.Context, gladiator *domainModel.Gladiator, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonResult, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "core.service.gladiator.Impl.Play",
		"input": input,
	})

	model, err := i.modelDAO.GetModelByName(ctx, gladiator.Model.Name)
	if err != nil {
		logger.WithError(err).Error("get model by name failed")
		return &domainModel.ArenaComparisonResult{
			ErrorMessage: err.Error(),
		}, nil
	}
	if model == nil {
		return &domainModel.ArenaComparisonResult{
			ErrorMessage: errors.ErrModelNotFound.Error(),
		}, nil
	}
	begin := time.Now()
	resp, err := i.modelGatewayRPC.Chat(ctx, &dto.ChatRequest{
		ModelName: model.GetRPCName(),
		Messages: []*dto.ChatRequestMessage{
			{
				Content: populateTemplate(gladiator.Prompt.Template, input.PromptVariables),
				Role:    dto.ChatRequestMessageRoleUser,
			},
		},
	})
	elapsed := time.Since(begin).Milliseconds()
	gladiatorName, _ := lo.Coalesce(gladiator.Name, model.DisplayName)
	ret := &domainModel.ArenaComparisonResult{
		GladiatorName: gladiatorName,
		Elapsed:       &domainModel.Elapsed{TotalMs: elapsed},
	}
	if err != nil {
		logger.WithError(err).Error("chat failed")
		ret.ErrorMessage = err.Error()
	}
	if resp == nil {
		return ret, nil
	}

	ret.AIMessage = resp.GetContent(true)

	if resp.Usage != nil {
		ret.Usage = &domainModel.Usage{
			InputTokenCount:  resp.Usage.InputTokenCount,
			OutputTokenCount: resp.Usage.OutputTokenCount,
		}
	}
	return ret, nil
}

func populateTemplate(template string, variables domainModel.PromptVariables) string {
	m := variables.ToMap()
	return variablePattern.ReplaceAllStringFunc(template, func(match string) string {
		variable := match[2 : len(match)-2]
		return m[strings.TrimSpace(variable)]
	})
}
