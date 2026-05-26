package handler_zhihu

import (
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	dashboard "git.in.zhihu.com/zhihu/aisp-core/pkg/business/dashboard_zhihu"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/samber/lo"
)

type ArenasHandler struct {
	rest.BaseHandler

	arenaBiz dashboard.ArenaBiz
}

func NewArenasHandler() rest.Handler {
	return &ArenasHandler{
		arenaBiz: dashboard.DefaultArenaBiz,
	}
}

func (h *ArenasHandler) Get(ctx *rest.Context) (rest.Response, error) {
	pageSize := ctx.Int64QueryArgument("page_size", 20)
	pageToken := ctx.QueryArgumentWithFallback("page_token", "")

	var offset int64
	if pageToken != "" {
		var err error
		offset, err = utils.ParseInt64(pageToken)
		if err != nil {
			return nil, rest.NewMalformRequestException("invalid page_token", nil, nil)
		}
	}
	arenas, count, err := h.arenaBiz.QueryArena(ctx, &dashboard.QueryRequest{
		Offset: offset,
		Limit:  pageSize,
	})
	if err != nil {
		return nil, err
	}
	return ResponsePagingSuccess(lo.Map(arenas, func(arena *domainModel.Arena, _ int) *ArenaDTO {
		return toArenaDTO(ctx, arena)
	}), lo.Ternary(len(arenas) < int(pageSize), "", util.Int64ToStr(offset+pageSize)), count)
}

func (h *ArenasHandler) Post(ctx *rest.Context) (rest.Response, error) {
	var arenaDTO *ArenaDTO
	err := ctx.JSONArgs(&arenaDTO)
	if err != nil {
		return nil, err
	}
	currentUser := middleware.UserFromContext(ctx)
	arena := &domainModel.Arena{
		Name:       arenaDTO.Name,
		OwnerEmail: currentUser.User.Email,
		Gladiators: lo.Map(arenaDTO.Gladiators, func(gladiatorDTO *ArenaGladiatorDTO, _ int) *domainModel.Gladiator {
			return &domainModel.Gladiator{
				Name: gladiatorDTO.Name,
				Model: &domainModel.GladiatorModel{
					Name: gladiatorDTO.Model.Name,
				},
				Prompt: &domainModel.GladiatorPrompt{
					Template: gladiatorDTO.Prompt.Template,
				},
			}
		}),
		State: domainModel.ArenaStateWaiting,
	}
	_, err = h.arenaBiz.CreateArena(ctx, arena)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(toArenaDTO(ctx, arena))
}

type ArenaDetailHandler struct {
	rest.BaseHandler

	arenaBiz dashboard.ArenaBiz
}

func NewArenaDetailHandler() rest.Handler {
	return &ArenaDetailHandler{
		arenaBiz: dashboard.DefaultArenaBiz,
	}
}

func (h *ArenaDetailHandler) Get(ctx *rest.Context) (rest.Response, error) {
	arenaIDStr := ctx.URLParam("arenaID")
	arenaID, err := utils.ParseInt64(arenaIDStr)
	if err != nil {
		return nil, rest.NewMalformRequestException("invalid arena id", nil, nil)
	}
	arena, err := h.arenaBiz.GetArena(ctx, arenaID)
	if err != nil {
		return nil, err
	}
	if arena == nil {
		return nil, rest.HttpNotFoundError
	}
	return ResponseSuccess(toArenaDTO(ctx, arena))
}

func (h *ArenaDetailHandler) Put(ctx *rest.Context) (rest.Response, error) {
	arenaIDStr := ctx.URLParam("arenaID")
	arenaID, err := utils.ParseInt64(arenaIDStr)
	if err != nil {
		return nil, rest.NewMalformRequestException("invalid arena id", nil, nil)
	}
	var arenaDTO *ArenaDTO
	err = ctx.JSONArgs(&arenaDTO)
	if err != nil {
		return nil, err
	}
	currentUser := middleware.UserFromContext(ctx)
	arena := &domainModel.Arena{
		ID:         arenaID,
		Name:       arenaDTO.Name,
		OwnerEmail: currentUser.User.Email,
		Gladiators: lo.Map(arenaDTO.Gladiators, func(gladiatorDTO *ArenaGladiatorDTO, _ int) *domainModel.Gladiator {
			return &domainModel.Gladiator{
				Name: gladiatorDTO.Name,
				Model: &domainModel.GladiatorModel{
					Name: gladiatorDTO.Model.Name,
				},
				Prompt: &domainModel.GladiatorPrompt{
					Template: gladiatorDTO.Prompt.Template,
				},
			}
		}),
	}
	err = h.arenaBiz.UpdateArena(ctx, arena)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(toArenaDTO(ctx, arena))
}

type ArenaDetailPlayHandler struct {
	rest.BaseHandler

	arenaBiz dashboard.ArenaBiz
}

func NewArenaDetailPlayHandler() rest.Handler {
	return &ArenaDetailPlayHandler{
		arenaBiz: dashboard.DefaultArenaBiz,
	}
}

func (h *ArenaDetailPlayHandler) Post(ctx *rest.Context) (rest.Response, error) {
	arenaIDStr := ctx.URLParam("arenaID")
	arenaID, err := utils.ParseInt64(arenaIDStr)
	if err != nil {
		return nil, rest.NewMalformRequestException("invalid arena id", nil, nil)
	}

	var variableDTOs []*ArenaPromptVariableDTO
	err = ctx.JSONArgs(&variableDTOs)
	if err != nil {
		return nil, err
	}

	output, err := h.arenaBiz.PlayByArena(
		ctx,
		arenaID,
		&domainModel.ArenaComparisonInput{
			PromptVariables: lo.Map(variableDTOs, func(variableDTO *ArenaPromptVariableDTO, _ int) *domainModel.PromptVariable {
				return &domainModel.PromptVariable{
					Name:  variableDTO.Name,
					Value: variableDTO.Value,
				}
			}),
		},
	)
	if errors.Is(err, dashboard.ErrArenaNotFound) {
		return nil, rest.HttpNotFoundError
	}
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(lo.Map(output.Results, func(result *domainModel.ArenaComparisonResult, _ int) *ArenaPlayResponseDTO {
		ret := &ArenaPlayResponseDTO{
			GladiatorName: result.GladiatorName,
			AIMessage:     result.AIMessage,
		}
		if result.ErrorMessage != "" {
			ret.ErrorMessage = result.ErrorMessage
		}
		if result.Usage != nil {
			ret.Usage = &ArenaPlayUsageDTO{
				InputTokenCount:  result.Usage.InputTokenCount,
				OutputTokenCount: result.Usage.OutputTokenCount,
			}
		}
		if result.Elapsed != nil {
			ret.Elapsed = &ArenaPlayElapsedDTO{TotalMs: result.Elapsed.TotalMs}
		}

		return ret
	}))
}

// {{variableName}}
var variablePattern = regexp.MustCompile(`{{\s*([^}]+?)\s*}}`)

func extractVariables(template string) []string {
	return lo.Uniq(lo.Map(variablePattern.FindAllStringSubmatch(template, -1), func(item []string, _ int) string {
		return item[1]
	}))
}

func normalizeTemplate(template string) string {
	return variablePattern.ReplaceAllString(template, "{{ $1 }}")
}

func toArenaDTO(ctx context.Context, arena *domainModel.Arena) *ArenaDTO {
	if arena == nil {
		return nil
	}

	variables := lo.Uniq(lo.Flatten(lo.Map(arena.Gladiators, func(gladiator *domainModel.Gladiator, _ int) []string {
		return extractVariables(gladiator.Prompt.Template)
	})))

	return &ArenaDTO{
		ID:         arena.ID,
		Name:       arena.Name,
		State:      string(arena.State),
		OwnerEmail: arena.OwnerEmail,
		Prompt: &ArenaPromptDTO{
			Variables: lo.Map(variables, func(variable string, _ int) *ArenaPromptVariableDTO {
				return &ArenaPromptVariableDTO{
					Name: variable,
				}
			}),
		},
		Gladiators: lo.Map(arena.Gladiators, func(gladiator *domainModel.Gladiator, _ int) *ArenaGladiatorDTO {
			modelDisplayName := gladiator.Model.Name
			model, err := dao.DefaultModelDAO.GetModelByName(ctx, gladiator.Model.Name)
			if err == nil && model != nil {
				modelDisplayName = model.DisplayName
			}

			return &ArenaGladiatorDTO{
				Name: gladiator.Name,
				Model: &ArenaGladiatorModelDTO{
					Name:        gladiator.Model.Name,
					DisplayName: modelDisplayName,
				},
				Prompt: &ArenaGladiatorPromptDTO{
					Template: gladiator.Prompt.Template,
				},
				Score: lo.Ternary(arena.Scores != nil, lo.ToPtr(arena.Scores[gladiator.Name]), nil),
			}
		}),
		Progress:           arena.Progress,
		ShotCount:          arena.ShotCount,
		ProcessedShotCount: arena.ProcessedShotCount,
	}
}

type ArenaDTO struct {
	ID                 int64                `json:"id,string"`
	Name               string               `json:"name"`
	State              string               `json:"state"`
	OwnerEmail         string               `json:"owner_email"`
	Prompt             *ArenaPromptDTO      `json:"prompt"`
	Gladiators         []*ArenaGladiatorDTO `json:"gladiators"`
	Scores             map[string]float64   `json:"scores,omitempty"`
	Progress           int64                `json:"progress,omitempty"`
	ShotCount          int64                `json:"shot_count,omitempty"`
	ProcessedShotCount int64                `json:"processed_shot_count,omitempty"`
}

type ArenaGladiatorDTO struct {
	Name   string                   `json:"name"`
	Model  *ArenaGladiatorModelDTO  `json:"model"`
	Prompt *ArenaGladiatorPromptDTO `json:"prompt"`
	Score  *float64                 `json:"score,omitempty"`
}

type ArenaGladiatorModelDTO struct {
	Name        string `json:"name"`
	DisplayName string `json:"display_name"`
}

type ArenaGladiatorPromptDTO struct {
	Template  string                    `json:"template"`
	Variables []*ArenaPromptVariableDTO `json:"variables,omitempty"`
	Populated string                    `json:"populated,omitempty"`
}

type ArenaPromptDTO struct {
	Variables []*ArenaPromptVariableDTO `json:"variables"`
}

type ArenaPromptVariableDTO struct {
	Name  string `json:"name"`
	Value string `json:"value,omitempty"`
}

type ArenasPlayHandler struct {
	rest.BaseHandler

	arenaBiz dashboard.ArenaBiz
}

func NewArenasPlayHandler() rest.Handler {
	return &ArenasPlayHandler{
		arenaBiz: dashboard.DefaultArenaBiz,
	}
}

func (h *ArenasPlayHandler) Post(ctx *rest.Context) (rest.Response, error) {
	var gladiator *ArenaGladiatorDTO
	err := ctx.JSONArgs(&gladiator)
	if err != nil {
		return nil, err
	}

	result, err := h.arenaBiz.PlayByGladiator(
		ctx, &domainModel.Gladiator{
			Name: gladiator.Name,
			Model: &domainModel.GladiatorModel{
				Name: gladiator.Model.Name,
			},
			Prompt: &domainModel.GladiatorPrompt{
				Template: gladiator.Prompt.Template,
			},
		},
		&domainModel.ArenaComparisonInput{
			PromptVariables: lo.Map(gladiator.Prompt.Variables, func(variable *ArenaPromptVariableDTO, _ int) *domainModel.PromptVariable {
				return &domainModel.PromptVariable{
					Name:  variable.Name,
					Value: variable.Value,
				}
			}),
		},
	)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(&ArenaPlayResponseDTO{
		AIMessage: result.AIMessage,
		Usage: &ArenaPlayUsageDTO{
			InputTokenCount:  result.Usage.InputTokenCount,
			OutputTokenCount: result.Usage.OutputTokenCount,
		},
		Elapsed: &ArenaPlayElapsedDTO{TotalMs: result.Elapsed.TotalMs},
	})
}

func populateTemplate(template string, variables map[string]string) string {
	return variablePattern.ReplaceAllStringFunc(template, func(match string) string {
		variable := match[2 : len(match)-2]
		return variables[strings.TrimSpace(variable)]
	})
}

type ArenaPlayResponseDTO struct {
	GladiatorName string               `json:"gladiator_name,omitempty"`
	ErrorMessage  string               `json:"error_message,omitempty"`
	AIMessage     string               `json:"ai_message"`
	Usage         *ArenaPlayUsageDTO   `json:"usage"`
	Elapsed       *ArenaPlayElapsedDTO `json:"elapsed"`
}

type ArenaPlayUsageDTO struct {
	InputTokenCount  int64 `json:"input_token_count"`
	OutputTokenCount int64 `json:"output_token_count"`
}

type ArenaPlayElapsedDTO struct {
	TotalMs int64 `json:"total_ms"`
}

type ArenasMatchHandler struct {
	rest.BaseHandler

	arenaBiz dashboard.ArenaBiz
}

func NewArenasMatchHandler() rest.Handler {
	return &ArenasMatchHandler{
		arenaBiz: dashboard.DefaultArenaBiz,
	}
}

func (h *ArenasMatchHandler) Get(ctx *rest.Context) (rest.Response, error) {
	ctx.Writer.Header()["Content-Type"] = []string{"text/csv"}
	ctx.Writer.Header()["Content-Disposition"] = []string{"attachment; filename=result.csv"}
	arenaIDStr := ctx.URLParam("arenaID")
	arenaID, err := utils.ParseInt64(arenaIDStr)
	if err != nil {
		return nil, rest.NewMalformRequestException("invalid arena id", nil, nil)
	}
	err = h.arenaBiz.GetArenaResult(ctx, arenaID, ctx.Writer)
	if err != nil {
		return nil, err
	}
	return EmptyResult, nil
}

func (h *ArenasMatchHandler) Post(ctx *rest.Context) (rest.Response, error) {
	arenaIDStr := ctx.URLParam("arenaID")
	arenaID, err := utils.ParseInt64(arenaIDStr)
	if err != nil {
		return nil, rest.NewMalformRequestException("invalid arena id", nil, nil)
	}

	file, _, err := ctx.Request.FormFile("file.csv")
	if err != nil {
		return nil, err
	}
	defer file.Close()

	recordsChan := make(chan map[string]string, 8192)
	err = util.CSVToChanMaps(file, recordsChan)
	close(recordsChan)
	if err != nil {
		return nil, err
	}
	records := lo.ChannelToSlice(recordsChan)
	if len(records) == 0 {
		return nil, rest.NewMalformRequestException("empty file", nil, nil)
	}

	err = h.arenaBiz.SubmitJob(ctx, arenaID, lo.Map(records, func(record map[string]string, _ int) *domainModel.ArenaComparisonInput {
		answer := record["正确答案 (没有则不填)"]
		delete(record, "正确答案 (没有则不填)")

		return &domainModel.ArenaComparisonInput{
			PromptVariables: lo.Map(lo.Entries(record), func(entry lo.Entry[string, string], _ int) *domainModel.PromptVariable {
				return &domainModel.PromptVariable{
					Name:  entry.Key,
					Value: entry.Value,
				}
			}),
			Answer: answer,
		}
	}))
	if errors.Is(err, dashboard.ErrArenaNotFound) {
		return nil, rest.HttpNotFoundError
	}
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(nil)
}

type ArenasMatchInputTemplateHandler struct {
	rest.BaseHandler

	arenaBiz dashboard.ArenaBiz
}

func NewArenasMatchInputTemplateHandler() rest.Handler {
	return &ArenasMatchInputTemplateHandler{
		arenaBiz: dashboard.DefaultArenaBiz,
	}
}

func (h *ArenasMatchInputTemplateHandler) Get(ctx *rest.Context) (rest.Response, error) {
	arenaIDStr := ctx.URLParam("arenaID")
	arenaID, err := utils.ParseInt64(arenaIDStr)
	if err != nil {
		return nil, rest.NewMalformRequestException("invalid arena id", nil, nil)
	}
	arena, err := h.arenaBiz.GetArena(ctx, arenaID)
	if err != nil {
		return nil, err
	}
	if arena == nil {
		return nil, rest.HttpNotFoundError
	}

	ctx.Writer.Header()["Content-Type"] = []string{"text/csv"}
	ctx.Writer.Header()["Content-Disposition"] = []string{fmt.Sprintf("attachment; filename*=utf-8''%s.csv", url.QueryEscape(arena.Name))}

	csvWriter := csv.NewWriter(ctx.Writer)

	variables := append(lo.Uniq(lo.Flatten(lo.Map(arena.Gladiators, func(gladiator *domainModel.Gladiator, _ int) []string {
		return extractVariables(gladiator.Prompt.Template)
	}))), "正确答案 (没有则不填)")

	csvWriter.Write(variables)
	for i := 0; i != 3; i++ {
		csvWriter.Write(lo.Map(variables, func(variable string, _ int) string {
			return fmt.Sprintf("第 %d 条评测 case 的 %s 的值", i+1, variable)
		}))
	}
	csvWriter.Flush()
	if err != nil {
		return nil, err
	}
	return EmptyResult, nil
}

type ArenasParsePromptHandler struct {
	rest.BaseHandler
}

func NewArenasParsePromptHandler() rest.Handler {
	return &ArenasParsePromptHandler{}
}

func (h *ArenasParsePromptHandler) Post(ctx *rest.Context) (rest.Response, error) {
	mode := ctx.QueryArgumentWithFallback("mode", "extract-variables")
	var prompt *ArenaGladiatorPromptDTO
	err := ctx.JSONArgs(&prompt)
	if err != nil {
		return nil, err
	}

	if mode == "populate-variables" {
		variables := lo.FromEntries(lo.Map(prompt.Variables, func(variable *ArenaPromptVariableDTO, _ int) lo.Entry[string, string] {
			return lo.Entry[string, string]{variable.Name, variable.Value}
		}))
		prompt.Populated = populateTemplate(prompt.Template, variables)
		return ResponseSuccess(prompt)
	}

	variables := extractVariables(prompt.Template)
	prompt.Variables = lo.Map(variables, func(variable string, _ int) *ArenaPromptVariableDTO {
		return &ArenaPromptVariableDTO{
			Name: variable,
		}
	})
	prompt.Template = normalizeTemplate(prompt.Template)
	return ResponseSuccess(prompt)
}

type ArenasMultiPlayHandler struct {
	rest.BaseHandler

	arenaBiz dashboard.ArenaBiz
}

func NewArenasMultiPlayHandler() rest.Handler {
	return &ArenasMultiPlayHandler{
		arenaBiz: dashboard.DefaultArenaBiz,
	}
}

type MultiPlayRequest struct {
	Gladiators []*ArenaGladiatorDTO      `json:"gladiators"`
	Variables  []*ArenaPromptVariableDTO `json:"variables"`
}

func (h *ArenasMultiPlayHandler) Post(ctx *rest.Context) (rest.Response, error) {
	var request *MultiPlayRequest
	err := ctx.JSONArgs(&request)
	if err != nil {
		return nil, err
	}

	output, err := h.arenaBiz.PlayByGladiators(
		ctx,
		lo.Map(request.Gladiators, func(gladiator *ArenaGladiatorDTO, _ int) *domainModel.Gladiator {
			template := "{{ Prompt }}"
			if gladiator.Prompt != nil {
				template = gladiator.Prompt.Template
			}
			return &domainModel.Gladiator{
				Name: gladiator.Name,
				Model: &domainModel.GladiatorModel{
					Name: gladiator.Model.Name,
				},
				Prompt: &domainModel.GladiatorPrompt{
					Template: template,
				},
			}
		}),
		&domainModel.ArenaComparisonInput{
			PromptVariables: lo.Map(request.Variables, func(variable *ArenaPromptVariableDTO, _ int) *domainModel.PromptVariable {
				return &domainModel.PromptVariable{
					Name:  variable.Name,
					Value: variable.Value,
				}
			}),
		},
	)
	if err != nil {
		return nil, err
	}
	return ResponseSuccess(lo.Map(output.Results, func(result *domainModel.ArenaComparisonResult, _ int) *ArenaPlayResponseDTO {
		ret := &ArenaPlayResponseDTO{
			GladiatorName: result.GladiatorName,
			AIMessage:     result.AIMessage,
		}
		if result.ErrorMessage != "" {
			ret.ErrorMessage = result.ErrorMessage
		}
		if result.Usage != nil {
			ret.Usage = &ArenaPlayUsageDTO{
				InputTokenCount:  result.Usage.InputTokenCount,
				OutputTokenCount: result.Usage.OutputTokenCount,
			}
		}
		if result.Elapsed != nil {
			ret.Elapsed = &ArenaPlayElapsedDTO{TotalMs: result.Elapsed.TotalMs}
		}

		return ret
	}))
}
