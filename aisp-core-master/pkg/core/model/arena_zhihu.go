package model

import (
	"time"

	"github.com/samber/lo"
)

type Arena struct {
	ID                 int64              `json:"id"`
	Name               string             `json:"name"`
	OwnerEmail         string             `json:"owner_email"`
	State              ArenaState         `json:"state"`
	Gladiators         []*Gladiator       `json:"gladiators"`
	Result             string             `json:"result"`
	Progress           int64              `json:"progress"`
	ShotCount          int64              `json:"shot_count"`
	ProcessedShotCount int64              `json:"processed_shot_count"`
	Scores             map[string]float64 `json:"scores"`
}

type ArenaState string

const (
	ArenaStateWaiting  ArenaState = "WAITING"
	ArenaStateRunning  ArenaState = "RUNNING"
	ArenaStateFinished ArenaState = "FINISHED"
	ArenaStateFail     ArenaState = "FAIL"
)

type ArenaJobState string

const (
	ArenaJobStateProcessing ArenaJobState = "PROCESSING"
	ArenaJobStateFinished   ArenaJobState = "SUCCESS"
	ArenaJobStateFail       ArenaJobState = "FAIL"
)

type Gladiator struct {
	Name   string           `json:"name"`
	Model  *GladiatorModel  `json:"model"`
	Prompt *GladiatorPrompt `json:"prompt"`
}

type GladiatorModel struct {
	Name string `json:"name"`
}

type GladiatorPrompt struct {
	Template string `json:"template"`
}

type ArenaJob struct {
	ID            int64         `json:"id"`
	ArenaID       int64         `json:"arena_id"`
	ArenaSnapshot *Arena        `json:"arena_snapshot"`
	State         ArenaJobState `json:"state"`
	CreatedAt     time.Time     `json:"created_at"`
	UpdatedAt     time.Time     `json:"updated_at"`
}

// ArenaShot is a comparison shot between two gladiators.
type ArenaShot struct {
	ID        int64                  `json:"id"`
	JobID     int64                  `json:"job_id"`
	State     ArenaShotState         `json:"state"`
	Error     error                  `json:"error"`
	Input     *ArenaComparisonInput  `json:"input"`
	Output    *ArenaComparisonOutput `json:"output"`
	CreatedAt time.Time              `json:"created_at"`
	UpdatedAt time.Time              `json:"updated_at"`
}

// ArenaComparisonInput is the Input of a comparison shot between two gladiators.
type ArenaComparisonInput struct {
	Answer          string          `json:"answer"`
	PromptVariables PromptVariables `json:"prompt_variables"`
}

type ArenaComparisonOutput struct {
	Results []*ArenaComparisonResult `json:"results"`
}

type ArenaComparisonResult struct {
	GladiatorName string   `json:"gladiator_name"`
	ErrorMessage  string   `json:"error_message"`
	AIMessage     string   `json:"ai_message"`
	Usage         *Usage   `json:"usage"`
	Elapsed       *Elapsed `json:"elapsed"`
}

type Elapsed struct {
	TotalMs int64 `json:"total_ms"`
}

type Usage struct {
	InputTokenCount  int64 `json:"input_token_count"`
	OutputTokenCount int64 `json:"output_token_count"`
}

type ArenaShotState string

const (
	ArenaShotStateWaiting    ArenaShotState = "WAITING"
	ArenaShotStateProcessing ArenaShotState = "PROCESSING"
	ArenaShotStateFinished   ArenaShotState = "SUCCESS"
	ArenaShotStateFail       ArenaShotState = "FAIL"
)

type PromptVariable struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

type PromptVariables []*PromptVariable

func (p PromptVariables) ToMap() map[string]string {
	return lo.FromEntries(lo.Map(p, func(variable *PromptVariable, _ int) lo.Entry[string, string] {
		return lo.Entry[string, string]{variable.Name, variable.Value}
	}))
}

func (p PromptVariables) Get(name string) string {
	for _, variable := range p {
		if variable.Name == name {
			return variable.Value
		}
	}
	return ""
}

type AsyncInvocation struct {
	ID     int64                `json:"id"`
	Fn     string               `json:"fn"`
	Params string               `json:"params"`
	State  AsyncInvocationState `json:"state"`
	Result string               `json:"result"`
	Error  string               `json:"error"`
}

type AsyncInvocationState string

const (
	AsyncInvocationStatePending     AsyncInvocationState = "PENDING"
	AsyncInvocationStateDistributed AsyncInvocationState = "DISTRIBUTED"
	AsyncInvocationStateProcessing  AsyncInvocationState = "PROCESSING"
	AsyncInvocationStateSuccess     AsyncInvocationState = "SUCCESS"
	AsyncInvocationStateFail        AsyncInvocationState = "FAIL"
)
