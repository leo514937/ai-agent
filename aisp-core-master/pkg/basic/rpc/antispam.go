package rpc

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-antispam-prod-api/antispam-prod-api"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type AntispamRPC interface {
	IsSpam(ctx context.Context, userID int64, headers map[string][]string) (bool, error)
}

var DefaultAntispamRPC AntispamRPC

type AntispamRPCImpl struct {
	client proto.AntispamApiServiceClient
}

func NewAntispamRPC() AntispamRPC {
	target := "antispam-prod-api-grpc"
	ctx := context.Background()

	logger := log.WithField(ctx, "target", target)

	conn, err := grpc.DialContext(context.Background(), target)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "dial antispam-prod-api-grpc failed")

		panic(err)
	}
	return &AntispamRPCImpl{
		client: proto.NewAntispamApiServiceClient(conn),
	}
}

func (r *AntispamRPCImpl) IsSpam(ctx context.Context, userID int64, reqContext map[string][]string) (bool, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"userID":     userID,
		"reqContext": reqContext,
	})

	ctx, cancel := context.WithTimeout(ctx, 1*time.Second)
	defer cancel()
	resp, err := r.client.CheckEvent(ctx, &proto.AntispamRequest{
		BusinessId: "1",
		SceneId:    "1",
		Timestamp:  time.Now().Unix(),
		MemberId:   userID,
		Ip:         getFromHeader(reqContext, "x-real-ip"),
		RuntimeId:  getFromHeader(reqContext, "x-zst-r"),
		Sdid:       getFromHeader(reqContext, "x-sdid"),
		SmDeviceId: getFromHeader(reqContext, "x-ms-id"),
		UserAgent:  getFromHeader(reqContext, "user-agent"),
		DeviceId:   "",
		Platform:   "",
		AppVersion: "",
		Target:     "",
		Content:    "",
		ContentId:  "",
		ExtraData:  "",
	})
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "antispam rpc failed")
		return true, err
	}

	logger.WithField(ctx, "resp", resp).Info(ctx, "antispam response")
	return resp.Code != 200, nil
}

func init() {
	DefaultAntispamRPC = NewAntispamRPC()
}

func getFromHeader(header map[string][]string, key string) string {
	value := ""
	v := header[key]
	if len(v) > 0 {
		value = v[0]
	}
	return value
}
