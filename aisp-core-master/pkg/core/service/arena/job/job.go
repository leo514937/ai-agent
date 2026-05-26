package job

import (
	"context"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type Service interface {
	CreateJob(ctx context.Context, job *domainModel.ArenaJob, inputs []*domainModel.ArenaComparisonInput) (int64, error)
	GetJob(ctx context.Context, jobID int64) (*domainModel.ArenaJob, error)
	GetLatestJobByArenaID(ctx context.Context, arenaID int64) (*domainModel.ArenaJob, error)

	RefreshJobState(ctx context.Context, jobID int64) (domainModel.ArenaJobState, error)
	GetJobProgress(ctx context.Context, jobID int64) (int64, error)
	GetJobProcessedShotCount(ctx context.Context, jobID int64) (int64, error)
	GetJobShotCount(ctx context.Context, jobID int64) (int64, error)

	GrabShot(ctx context.Context) (*domainModel.ArenaShot, error)
	ListFinishedShot(ctx context.Context, jobID int64) ([]*domainModel.ArenaShot, error)
	SubmitShot(ctx context.Context, shot *domainModel.ArenaShot) error
}

type Impl struct {
	arenaJobDAO  dao.ArenaJobDAO
	arenaShotDAO dao.ArenaShotDAO
}

var (
	_              Service = (*Impl)(nil)
	DefaultService Service = NewService()
)

func NewService() Service {
	return &Impl{
		arenaJobDAO:  dao.DefaultArenaJobDAO,
		arenaShotDAO: dao.DefaultArenaShotDAO,
	}
}

func (i *Impl) CreateJob(ctx context.Context, job *domainModel.ArenaJob, inputs []*domainModel.ArenaComparisonInput) (int64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "core.service.arena.job.Impl.CreateJob",
		"job":  job,
	})

	jobID, err := i.arenaJobDAO.CreateArenaJob(ctx, job)
	if err != nil {
		logger.WithError(err).Error("create arena job failed")
		return 0, err
	}
	for _, input := range inputs {
		_, err := i.arenaShotDAO.CreateArenaShot(ctx, &domainModel.ArenaShot{
			JobID: jobID,
			State: domainModel.ArenaShotStateWaiting,
			Input: input,
		})
		if err != nil {
			logger.WithField("input", input).WithError(err).Error("create arena shot failed")
			return 0, err
		}
	}
	return jobID, nil
}

func (i *Impl) GetJob(ctx context.Context, jobID int64) (*domainModel.ArenaJob, error) {
	return i.arenaJobDAO.GetArenaJobByID(ctx, jobID)
}

func (i *Impl) GetLatestJobByArenaID(ctx context.Context, arenaID int64) (*domainModel.ArenaJob, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":    "core.service.arena.job.Impl.GetLatestJobByArenaID",
		"arenaID": arenaID,
	})

	jobs, err := i.arenaJobDAO.ListArenaJobByArenaID(ctx, arenaID, 0, 1)
	if err != nil {
		logger.WithError(err).Error("list arena job by arena id failed")
		return nil, err
	}
	if len(jobs) == 0 {
		return nil, nil
	}
	return jobs[0], nil
}

func (i *Impl) GetJobProgress(ctx context.Context, jobID int64) (int64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "core.service.arena.job.Impl.GetJobProgress",
		"jobID": jobID,
	})
	processingCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateProcessing)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Processing) failed")
		return 0, err
	}
	waitingCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateWaiting)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Waiting) failed")
		return 0, err
	}
	if processingCount+waitingCount == 0 {
		return 100, nil
	}
	successCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateFinished)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Finished) failed")
		return 0, err
	}
	failCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateFail)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Fail) failed")
		return 0, err
	}
	return (successCount + failCount) * 100 / (processingCount + waitingCount + successCount + failCount), nil
}

func (i *Impl) GetJobProcessedShotCount(ctx context.Context, jobID int64) (int64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "core.service.arena.job.Impl.GetJobProcessedShotCount",
		"jobID": jobID,
	})
	successCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateFinished)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Finished) failed")
		return 0, err
	}
	failCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateFail)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Fail) failed")
		return 0, err
	}
	return successCount + failCount, nil
}

func (i *Impl) GetJobShotCount(ctx context.Context, jobID int64) (int64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "core.service.arena.job.Impl.GetJobShotCount",
		"jobID": jobID,
	})
	processingCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateProcessing)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Processing) failed")
		return 0, err
	}
	waitingCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateWaiting)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Waiting) failed")
		return 0, err
	}
	successCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateFinished)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Finished) failed")
		return 0, err
	}
	failCount, err := i.arenaShotDAO.CountArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateFail)
	if err != nil {
		logger.WithError(err).Error("count arena shot by job id (Fail) failed")
		return 0, err
	}
	return processingCount + waitingCount + successCount + failCount, nil
}

func (i *Impl) RefreshJobState(ctx context.Context, jobID int64) (domainModel.ArenaJobState, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "core.service.arena.job.Impl.RefreshJobState",
		"jobID": jobID,
	})

	shots, err := i.arenaShotDAO.ListArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateProcessing, 0, 1)
	if err != nil {
		logger.WithError(err).Error("list arena shot by arena id (processing) failed")
		return "", err
	}
	if len(shots) > 0 {
		err = i.arenaJobDAO.UpdateArenaJobState(ctx, jobID, domainModel.ArenaJobStateProcessing)
		if err != nil {
			logger.WithError(err).Error("update arena job state failed")
			return "", err
		}
		return domainModel.ArenaJobStateProcessing, nil
	}
	shots, err = i.arenaShotDAO.ListArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateWaiting, 0, 1)
	if err != nil {
		logger.WithError(err).Error("list arena shot by arena id (waiting) failed")
		return "", err
	}
	if len(shots) > 0 {
		err = i.arenaJobDAO.UpdateArenaJobState(ctx, jobID, domainModel.ArenaJobStateProcessing)
		if err != nil {
			logger.WithError(err).Error("update arena job state failed")
			return "", err
		}
		return domainModel.ArenaJobStateProcessing, nil
	}
	err = i.arenaJobDAO.UpdateArenaJobState(ctx, jobID, domainModel.ArenaJobStateFinished)
	if err != nil {
		logger.WithError(err).Error("update arena job state failed")
		return "", err
	}
	return domainModel.ArenaJobStateFinished, nil
}

func (i *Impl) GrabShot(ctx context.Context) (*domainModel.ArenaShot, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "core.service.arena.job.Impl.GrabShot",
	})
	shot, err := i.arenaShotDAO.LockArenaShot(ctx)
	if err != nil {
		logger.WithError(err).Error("lock arena shot failed")
		return nil, err
	}
	if shot == nil {
		return nil, nil
	}
	shot.State = domainModel.ArenaShotStateProcessing
	err = i.arenaShotDAO.UpdateArenaShot(ctx, shot)
	if err != nil {
		logger.WithError(err).Error("update arena shot failed")
		return nil, err
	}
	return shot, nil
}

func (i *Impl) ListFinishedShot(ctx context.Context, jobID int64) ([]*domainModel.ArenaShot, error) {
	shots, err := i.arenaShotDAO.ListArenaShotByJobID(ctx, jobID, domainModel.ArenaShotStateFinished, 0, 0)
	if err != nil {
		return nil, err
	}
	return shots, nil
}

func (i *Impl) SubmitShot(ctx context.Context, shot *domainModel.ArenaShot) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "core.service.arena.job.Impl.SubmitShot",
		"shot": shot,
	})
	if shot.Error != nil {
		logger.WithError(shot.Error).Error("arena shot failed")
		shot.State = domainModel.ArenaShotStateFail
	} else {
		shot.State = domainModel.ArenaShotStateFinished
	}
	err := i.arenaShotDAO.UpdateArenaShot(ctx, shot)
	if err != nil {
		logger.WithError(err).Error("update arena shot failed")
		return err
	}
	logger.Info("arena shot submitted")
	return nil
}
