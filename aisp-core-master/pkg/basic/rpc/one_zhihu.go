package rpc

import (
	"context"
	"crypto/hmac"
	"crypto/sha1"
	"encoding/base64"
	"fmt"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/imroc/req/v3"
	"github.com/samber/lo"
)

type OneRPC interface {
	GetAppByName(ctx context.Context, appName string) (*model.App, error)
	ListAppByName(ctx context.Context, appName string) ([]*model.App, error)
	ListAllBizLines(ctx context.Context) ([]*BizLineDO, error)
}

type BizLineDO struct {
	ID   string
	Name string
}

type OneRPCImpl struct {
	Client *req.Client

	secret  string
	appName string
}

var (
	_             OneRPC = (*OneRPCImpl)(nil)
	DefaultOneRPC OneRPC = NewOneRPC()
)

var configClient = config.GetClient()

func NewOneRPC() *OneRPCImpl {
	ret := &OneRPCImpl{
		secret:  configClient.GetString("one_secret"),
		appName: configClient.GetString("one_app_name"),
	}

	ret.Client = req.C().
		OnBeforeRequest(func(c *req.Client, r *req.Request) error {
			reqTime := util.Int64ToStr(time.Now().Unix() * 10000) // I don't know why it's 10000, just make one.in happy
			token := ret.sign(reqTime)
			r.SetHeaders(map[string]string{
				"reqtime": reqTime,
				"token":   token,
				"name":    ret.appName,
			})
			return nil
		}).
		SetBaseURL("http://one.in.zhihu.com/api/externals/")

	return ret
}

type respWrapper[D any] struct {
	Code int64  `json:"code"`
	Msg  string `json:"msg"`
	Data D      `json:"data"`
}

func (r *OneRPCImpl) sign(value string) string {
	h := hmac.New(sha1.New, []byte(r.secret))
	_, _ = h.Write([]byte(value))

	return base64.StdEncoding.EncodeToString(h.Sum(nil))
}

func (r *OneRPCImpl) ListAllBizLines(ctx context.Context) ([]*BizLineDO, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.rpc.OneRPCImpl.ListAllBizLines",
	})

	resp := r.Client.
		Get(`/v2/business-line`).
		Do(ctx)
	if err := resp.ErrorResult(); err != nil {
		logger.WithField(ctx, "resp", resp).Error(ctx, "failed to list all biz lines")
		return nil, fmt.Errorf("failed to list all biz lines: %v", err)
	}

	result := &respWrapper[[]*OneBizLineDTO]{}
	err := resp.Unmarshal(result)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "unmarshal failed")
		return nil, err
	}
	return lo.Map(result.Data, func(dto *OneBizLineDTO, index int) *BizLineDO {
		return &BizLineDO{
			ID:   util.Int64ToStr(dto.ID),
			Name: dto.Name,
		}
	}), nil
}

type OneBizLineDTO struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

func (r *OneRPCImpl) ListAppByName(ctx context.Context, appName string) ([]*model.App, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.rpc.OneRPCImpl.ListAppByName",
	})

	resp := r.Client.Get(fmt.Sprintf(`/rd/v1/apps?q=%s&types=0&pageSize=50`, appName)).Do(ctx)
	if err := resp.ErrorResult(); err != nil {
		logger.WithField(ctx, "resp", resp).Error(ctx, "failed to list app by name")
		return nil, fmt.Errorf("failed to list app by name: %v", err)
	}

	result := &respWrapper[struct {
		List []*OneAppDTO `json:"list"`
	}]{}
	err := resp.Unmarshal(result)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "unmarshal failed")
		return nil, err
	}
	return lo.Map(result.Data.List, func(dto *OneAppDTO, index int) *model.App {
		return &model.App{
			Name:             dto.Name,
			OwnerEmail:       dto.Owner.Email,
			OwnerBizLineName: dto.Owner.DepartmentFullName,
		}
	}), nil
}

func (r *OneRPCImpl) GetAppByName(ctx context.Context, appName string) (*model.App, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":    "basic.rpc.OneRPCImpl.GetAppByName",
		"appName": appName,
	})
	resp := r.Client.Get(fmt.Sprintf(`/rd/v1/app/%s/detail?type=0`, appName)).Do(ctx)
	if err := resp.ErrorResult(); err != nil {
		logger.WithField(ctx, "resp", resp).Error(ctx, "failed to get app by name")
		return nil, fmt.Errorf("failed to get app by name: %v", err)
	}

	result := &respWrapper[OneAppDTO]{}
	err := resp.Unmarshal(result)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "unmarshal failed")
		return nil, err
	}
	return &model.App{
		Name:             result.Data.Name,
		OwnerEmail:       result.Data.Owner.Email,
		OwnerBizLineName: result.Data.Owner.DepartmentFullName,
	}, nil
}

type OneAppDTO struct {
	Name  string      `json:"name"`
	ID    int64       `json:"id"`
	Owner OneOwnerDTO `json:"owner"`
}

type OneOwnerDTO struct {
	DepartmentFullName string `json:"departmentFlat"`
	Email              string `json:"primaryEmail"`
}
