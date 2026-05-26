package dashboard

import (
	"context"
	"encoding/csv"
	"errors"
	"io"
	"time"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/arena"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/arena/gladiator"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/arena/job"
	"github.com/samber/lo"
)

var (
	ErrArenaNotFound = errors.New("arena not found")
)

type ArenaBiz interface {
	CreateArena(ctx context.Context, arena *domainModel.Arena) (int64, error)
	UpdateArena(ctx context.Context, arena *domainModel.Arena) error
	QueryArena(ctx context.Context, request *QueryRequest) ([]*domainModel.Arena, int64, error)
	GetArena(ctx context.Context, id int64) (*domainModel.Arena, error)
	PlayByArena(ctx context.Context, arenaID int64, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonOutput, error)
	PlayByGladiators(ctx context.Context, gladiators []*domainModel.Gladiator, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonOutput, error)
	PlayByGladiator(ctx context.Context, gladiator *domainModel.Gladiator, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonResult, error)
	SubmitJob(ctx context.Context, arenaID int64, intputs []*domainModel.ArenaComparisonInput) error
	GetArenaResult(ctx context.Context, arenaID int64, writer io.Writer) error
	ProcessShots(ctx context.Context, close <-chan struct{}) error
}

type QueryRequest struct {
	Offset int64
	Limit  int64
}

type PlayRequest struct {
	ArenaID   int64
	Variables []*domainModel.PromptVariable
}

type PlayResponse struct {
	Results []*PlayResult
}

type PlayResult struct {
	GladiatorName string
	ErrorMessage  string
	AIMessage     string
	Usage         *PlayResultUsage
	Elapsed       *PlayResultElapsed
}

type PlayResultUsage struct {
	InputTokenCount  int64
	OutputTokenCount int64
}

type PlayResultElapsed struct {
	TotalMs int64 `json:"total_ms"`
}

type ArenaBizImpl struct {
	arenaDAO         dao.ArenaDAO
	arenaService     arena.Service
	jobService       job.Service
	gladiatorService gladiator.Service
	shotRateLimiter  util.DynamicRateLimiter
}

var (
	_               ArenaBiz = (*ArenaBizImpl)(nil)
	DefaultArenaBiz ArenaBiz = NewArenaBizImpl()
)

func NewArenaBizImpl() *ArenaBizImpl {
	return &ArenaBizImpl{
		arenaDAO:         dao.DefaultArenaDAO,
		arenaService:     arena.DefaultService,
		jobService:       job.DefaultService,
		gladiatorService: gladiator.DefaultService,
		shotRateLimiter: util.NewDynamicRateLimiter(func() float64 {
			return float64(config.GetInt("dashboard.arena.shot_rate_limit", 5))
		}),
	}
}

func (b *ArenaBizImpl) CreateArena(ctx context.Context, arena *domainModel.Arena) (int64, error) {
	return b.arenaDAO.CreateArena(ctx, arena)
}

func (b *ArenaBizImpl) UpdateArena(ctx context.Context, arena *domainModel.Arena) error {
	return b.arenaDAO.UpdateArena(ctx, arena)
}

func (b *ArenaBizImpl) QueryArena(ctx context.Context, request *QueryRequest) ([]*domainModel.Arena, int64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":    "dashboard.biz.arena.QueryArena",
		"request": request,
	})
	arenas, err := b.arenaDAO.ListArena(ctx, request.Offset, request.Limit)
	if err != nil {
		logger.WithError(err).Error("failed to list arena")
		return nil, 0, err
	}
	count, err := b.arenaDAO.CountArena(ctx)
	if err != nil {
		logger.WithError(err).Error("failed to count arena")
		return nil, 0, err
	}
	for _, arena := range arenas {
		err := b.populateArenaProgress(ctx, arena)
		if err != nil {
			logger.WithError(err).Error("failed to populate arena progress")
			return nil, 0, err
		}
	}
	return arenas, count, nil
}

func (b *ArenaBizImpl) populateArenaProgress(ctx context.Context, arena *domainModel.Arena) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "dashboard.biz.arena.populateArenaProgress",
		"arena": arena,
	})

	job, err := b.jobService.GetLatestJobByArenaID(ctx, arena.ID)
	if err != nil {
		logger.WithError(err).Error("failed to get latest job")
		return err
	}
	if job == nil {
		return nil
	}
	progress, err := b.jobService.GetJobProgress(ctx, job.ID)
	if err != nil {
		logger.WithError(err).Error("failed to get job progress")
		return err
	}
	arena.Progress = progress
	shotCount, err := b.jobService.GetJobShotCount(ctx, job.ID)
	if err != nil {
		logger.WithError(err).Error("failed to get job shot count")
		return err
	}
	arena.ShotCount = shotCount
	shotProcessedCount, err := b.jobService.GetJobProcessedShotCount(ctx, job.ID)
	if err != nil {
		logger.WithError(err).Error("failed to get job processed shot count")
		return err
	}
	arena.ProcessedShotCount = shotProcessedCount
	return nil
}

func (b *ArenaBizImpl) GetArena(ctx context.Context, id int64) (*domainModel.Arena, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "dashboard.biz.arena.GetArena",
		"id":   id,
	})
	arena, err := b.arenaDAO.GetArenaByID(ctx, id)
	if err != nil {
		logger.WithError(err).Error("failed to get arena")
		return nil, err
	}
	if arena == nil {
		logger.Warn("arena not found")
		return nil, nil
	}
	job, err := b.jobService.GetLatestJobByArenaID(ctx, arena.ID)
	if err != nil {
		logger.WithError(err).Error("failed to get latest job")
		return nil, err
	}
	if job == nil {
		return arena, nil
	}

	err = b.populateArenaProgress(ctx, arena)
	if err != nil {
		logger.WithError(err).Error("failed to populate arena progress")
		return nil, err
	}

	scores, err := b.calcScores(ctx, job)
	if err != nil {
		logger.WithError(err).Error("failed to calc scores")
		return nil, err
	}
	arena.Scores = scores
	return arena, nil
}

func (b *ArenaBizImpl) calcScores(ctx context.Context, arenaJob *domainModel.ArenaJob) (map[string]float64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":     "dashboard.biz.arena.calcScores",
		"arenaJob": arenaJob,
	})

	if arenaJob.State != domainModel.ArenaJobStateFinished {
		return nil, nil
	}
	shots, err := b.jobService.ListFinishedShot(ctx, arenaJob.ID)
	if err != nil {
		logger.WithError(err).Error("failed to list finished shot")
		return nil, err
	}

	counter := map[string]int64{}
	for _, shot := range shots {
		if shot.Input.Answer == "" {
			return nil, nil
		}

		for i, result := range shot.Output.Results {
			if result.ErrorMessage != "" {
				continue
			}
			if result.AIMessage == shot.Input.Answer {
				counter[arenaJob.ArenaSnapshot.Gladiators[i].Name]++
			}
		}
	}

	return lo.MapValues(counter, func(value int64, _ string) float64 {
		return float64(value) / float64(len(shots))
	}), nil
}

func (b *ArenaBizImpl) PlayByArena(ctx context.Context, arenaID int64, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonOutput, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":    "dashboard.biz.arena.PlayByArena",
		"arenaID": arenaID,
		"input":   input,
	})
	arena, err := b.arenaDAO.GetArenaByID(ctx, arenaID)
	if err != nil {
		logger.WithError(err).Error("failed to get arena")
		return nil, err
	}
	if arena == nil {
		logger.Error("arena not found")
		return nil, ErrArenaNotFound
	}

	eg := utils.ErrorGroup{}
	results := make([]*domainModel.ArenaComparisonResult, len(arena.Gladiators))
	for i, gladiator := range arena.Gladiators {
		i := i
		gladiator := gladiator
		eg.Go(func() error {
			output, err := b.gladiatorService.Play(ctx, gladiator, input)
			if err != nil {
				return err
			}
			results[i] = output
			return nil
		})
	}
	if err := eg.Wait(); err != nil {
		return nil, err
	}
	return &domainModel.ArenaComparisonOutput{
		Results: results,
	}, nil
}

func (b *ArenaBizImpl) PlayByGladiators(ctx context.Context, gladiators []*domainModel.Gladiator, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonOutput, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":       "dashboard.biz.arena.PlayByGladiators",
		"gladiators": gladiators,
		"input":      input,
	})

	eg := utils.ErrorGroup{}
	results := make([]*domainModel.ArenaComparisonResult, len(gladiators))
	for i, gladiator := range gladiators {
		i := i
		gladiator := gladiator
		eg.Go(func() error {
			output, err := b.gladiatorService.Play(ctx, gladiator, input)
			if err != nil {
				return err
			}
			results[i] = output
			return nil
		})
	}
	if err := eg.Wait(); err != nil {
		logger.WithError(err).Error("failed to play by gladiators")
		return nil, err
	}
	return &domainModel.ArenaComparisonOutput{
		Results: results,
	}, nil
}

func (b *ArenaBizImpl) PlayByGladiator(ctx context.Context, gladiator *domainModel.Gladiator, input *domainModel.ArenaComparisonInput) (*domainModel.ArenaComparisonResult, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "dashboard.biz.arena.PlayByGladiator",
		"gladiator": gladiator,
		"input":     input,
	})

	result, err := b.gladiatorService.Play(ctx, gladiator, input)
	if err != nil {
		logger.WithError(err).Error("failed to play by gladiator")
		return nil, err
	}
	return result, nil
}

func (b *ArenaBizImpl) SubmitJob(ctx context.Context, arenaID int64, inputs []*domainModel.ArenaComparisonInput) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":    "dashboard.biz.arena.SubmitJob",
		"arenaID": arenaID,
	})

	arena, err := b.arenaDAO.GetArenaByID(ctx, arenaID)
	if err != nil {
		logger.WithError(err).Error("failed to get arena")
		return err
	}
	if arena == nil {
		logger.Error("arena not found")
		return ErrArenaNotFound
	}

	arena.State = domainModel.ArenaStateRunning
	err = b.arenaDAO.UpdateArena(ctx, arena)
	if err != nil {
		logger.WithError(err).Error(ctx, "failed to update arena state")
		return err
	}

	jobID, err := b.jobService.CreateJob(ctx, &domainModel.ArenaJob{
		ArenaID:       arenaID,
		ArenaSnapshot: arena,
		State:         domainModel.ArenaJobStateProcessing,
	}, inputs)
	if err != nil {
		logger.WithError(err).Error("failed to create job")
		return err
	}
	logger.WithField("jobID", jobID).Info("job created")
	return nil

	utils.SafelyGo(func() {

	}, func(err error) {
		logger.WithError(err).Error("failed to submit match")
	})
	return nil
}

func (b *ArenaBizImpl) ProcessShots(ctx context.Context, close <-chan struct{}) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "dashboard.biz.arena.ProcessShots",
	})

	for {
		select {
		case <-close:
			logger.Info("close signal received")
			return nil
		default:
			// do noting
		}

		b.shotRateLimiter.Wait(ctx)
		err := resource.MySQLAISPInternal.WithTxn(ctx, func() error {
			shot, err := b.jobService.GrabShot(ctx)
			if err != nil {
				logger.WithError(err).Error("failed to grab shot")
				return err
			}
			if shot == nil {
				time.Sleep(time.Millisecond * 100)
				return nil
			}

			err = b.ProcessShot(ctx, shot)
			if err != nil {
				logger.WithField("shot", shot).WithError(err).Error("failed to process shot")
				return err
			}

			state, err := b.jobService.RefreshJobState(ctx, shot.JobID)
			if err != nil {
				logger.WithError(err).Error("failed to refresh job state")
				return err
			}

			if state == domainModel.ArenaJobStateFinished {
				logger.WithField("jobID", shot.JobID).Info("job finished")
				job, err := b.jobService.GetJob(ctx, shot.JobID)
				if err != nil {
					logger.WithError(err).Error("failed to get job")
					return err
				}
				err = b.arenaService.UpdateArenaState(ctx, job.ArenaID, domainModel.ArenaStateFinished)
				if err != nil {
					logger.WithError(err).Error("failed to update arena state")
					return err
				}
			}
			return nil
		})
		if err != nil {
			logger.WithError(err).Error("failed to process shot")
		}

		time.Sleep(10 * time.Second)
	}
}

func (b *ArenaBizImpl) ProcessShot(ctx context.Context, shot *domainModel.ArenaShot) (err error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "dashboard.biz.arena.ProcessShot",
		"shot": shot,
	})

	begin := time.Now()
	statsd.Increment("aisp-core.dashboard.arena.shot.processing.count")

	if shot.State == domainModel.ArenaShotStateFinished {
		logger.Warn("shot already finished")
		return nil
	}
	defer func() {
		if err != nil {
			shot.State = domainModel.ArenaShotStateFail
			shot.Error = err
		} else {
			shot.State = domainModel.ArenaShotStateFinished
		}
		b.jobService.SubmitShot(ctx, shot)
	}()

	job, err := b.jobService.GetJob(ctx, shot.JobID)
	if err != nil {
		logger.WithError(err).Error("failed to get job")
		return err
	}

	if job == nil {
		logger.WithError(err).Error("job not found")
		return errors.New("job not found")
	}

	arena := job.ArenaSnapshot
	if arena == nil {
		logger.WithError(err).Error("arena not found")
		return errors.New("arena not found")
	}

	output, err := b.PlayByGladiators(ctx, arena.Gladiators, shot.Input)
	if err != nil {
		logger.WithError(err).Error("failed to play by gladiators")
		return err
	}
	shot.Output = output
	statsd.Increment("aisp-core.dashboard.arena.shot.processed.count")
	statsd.Timing("aisp-core.dashboard.arena.shot.processed.elapsed", time.Since(begin))
	return nil
}

func (b *ArenaBizImpl) GetArenaResult(ctx context.Context, arenaID int64, writer io.Writer) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":    "dashboard.biz.arena.GetArenaResult",
		"arenaID": arenaID,
	})

	arena, err := b.arenaDAO.GetArenaByID(ctx, arenaID)
	if err != nil {
		logger.WithError(err).Error("failed to get arena")
		return err
	}
	if arena == nil {
		logger.Error("arena not found")
		return ErrArenaNotFound
	}

	latestJob, err := b.jobService.GetLatestJobByArenaID(ctx, arenaID)
	if err != nil {
		logger.WithError(err).Error("failed to get latest job")
		return err
	}
	if latestJob == nil {
		if arena.Result != "" {
			_, err := io.WriteString(writer, arena.Result)
			if err != nil {
				logger.WithError(err).Error("failed to write result")
				return err
			}
		}

		logger.Error("latest job not found")
		return errors.New("latest job not found")
	}

	shots, err := b.jobService.ListFinishedShot(ctx, latestJob.ID)
	if err != nil {
		logger.WithError(err).Error("failed to list shot")
		return err
	}

	keys := []string{}
	writter := csv.NewWriter(writer)

	writeHeader := func(input *domainModel.ArenaComparisonInput) {
		writter.Write(append(keys, lo.Flatten(lo.Map(lo.Map(arena.Gladiators, func(gladiator *domainModel.Gladiator, _ int) string {
			return gladiator.Name
		}), func(item string, _ int) []string {
			return lo.Map(util.List("用时(ms)", "输出结果", "错误信息", "输入Token数", "输出Token数"), func(attr string, _ int) string {
				return item + "-" + attr
			})
		}))...))
	}
	for i, shot := range shots {
		if i == 0 {
			keys = lo.Map(shot.Input.PromptVariables, func(item *domainModel.PromptVariable, _ int) string {
				return item.Name
			})
			if shot.Input.Answer != "" {
				keys = append(keys, "标准答案")
			}
			writeHeader(shot.Input)
		}

		writter.Write(append(lo.Map(keys, func(key string, _ int) string {
			if key == "标准答案" {
				return shot.Input.Answer
			}
			return shot.Input.PromptVariables.Get(key)
		}), lo.Flatten(lo.Map(shot.Output.Results, func(result *domainModel.ArenaComparisonResult, _ int) []string {
			errorMessage := ""
			if result.ErrorMessage != "" {
				errorMessage = result.ErrorMessage
			}
			intputTokenCount := ""
			outputTokenCount := ""
			if result.Usage != nil {
				intputTokenCount = utils.Int64ToStr(result.Usage.InputTokenCount)
				outputTokenCount = utils.Int64ToStr(result.Usage.OutputTokenCount)
			}
			elapsed := ""
			if result.Elapsed != nil {
				elapsed = utils.Int64ToStr(result.Elapsed.TotalMs)
			}
			return util.List(elapsed, result.AIMessage, errorMessage, intputTokenCount, outputTokenCount)
		}))...))
	}

	writter.Flush()
	return nil
}
