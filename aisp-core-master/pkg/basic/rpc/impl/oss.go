package impl

import (
	"context"
	"encoding/base64"
	"net/http"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/thrift-go/zos_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type OssImpl struct {
	thriftClient *zos_thrift.ZosServiceClient
	httpClient   *util.HttpClient
}

var DefaultOssImpl rpc.Oss

func init() {
	DefaultOssImpl = NewOssHttp()
}
func NewOssHttp() rpc.Oss {
	return &OssImpl{
		thriftClient: zos_thrift.NewZosServiceClient(
			tzone.NewClient(
				"ZosService",
				tzone.TargetName("zos-rpc"),
				tzone.Timeout(1000*time.Millisecond),
			)),
		httpClient: util.NewHttpClient("", "", 3000*time.Millisecond),
	}
}

// GetFileBytes 调用对象存储，获得字节流
func (o *OssImpl) GetFileBytes(ctx context.Context, url string) ([]byte, error) {
	logger := log.WithField(ctx, "GetFileBytes", url)
	res, err := o.httpClient.DoGet(ctx, url, nil)
	if err != nil {
		logger.Errorf(ctx, "GetFileBytes failed: %v", err)
		return nil, err
	}

	return res, nil
}

func (o *OssImpl) GetFileBase64(ctx context.Context, url string) (string, error) {
	urlResponse, err := o.GetFileBytes(ctx, url)
	if err != nil {
		return "", err
	}
	imageBase64 := base64.StdEncoding.EncodeToString(urlResponse)
	return imageBase64, nil
}

// GetOssFilePath 获取对象存储文件路径
func (o *OssImpl) GetOssFilePath(ctx context.Context, key string, appName string, sceneName string, spaceName string) string {
	var resp string
	runFunc := func(ctx context.Context) (err error) {
		signURL, err := o.thriftClient.SignURL(ctx, &zos_thrift.SignURLReq{
			Context: &zos_thrift.RequestContext{
				AppName:   appName,
				SceneName: sceneName,
			},
			ObjectKey:  key,
			SpaceName:  spaceName,
			HttpMethod: http.MethodGet,
		})
		if err == nil && signURL != nil && signURL.URL != nil {
			resp = signURL.URL.GetPrimary()
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return resp
}

var _ rpc.Oss = (*OssImpl)(nil)
