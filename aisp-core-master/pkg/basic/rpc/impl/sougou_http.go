package impl

import (
	"context"
	"crypto/hmac"
	"crypto/md5"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/spf13/cast"
)

const (
	action        = "SearchAnswer"
	service       = "tms"
	host          = "tms.tencentcloudapi.com"
	region        = "default"
	version       = "2020-12-29"
	contentType   = "application/json; charset=utf-8"
	signedHeaders = "content-type;host"
	methodPost    = http.MethodPost
)

var (
	secretID  = config.GetString(macro.SougouSecretIdConfigName, "")
	secretKey = config.GetString(macro.SougouSecretKeyConfigName, "")
	pid       = config.GetString(macro.SougouPidConfigName, "")
	token     = config.GetString(macro.SougouTokenConfigName, "")
)

type SougouClientHttpImpl struct {
	httpClient *util.HttpClient
}

func NewSougouClientHttp() rpc.SougouClientHttp {
	return &SougouClientHttpImpl{
		httpClient: util.NewHttpClient(methodPost, fmt.Sprintf("https://%s", host), 1500*time.Millisecond),
	}
}

// SougouSearch 搜狗搜索
func (s *SougouClientHttpImpl) SougouSearch(ctx context.Context, query string, topK int32) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	logger := log.WithField(ctx, "SougouSearch", query)

	timestamp := time.Now().Unix()
	date := time.Now().UTC().Format("2006-01-02")

	salt := cast.ToString(time.Now().UnixNano() / 1e6)
	payloadParams := map[string]string{
		"Query": query,
		"Pid":   pid,
		"Sign":  s.generateMD5(pid, query, salt, token),
		"Salt":  salt,
	}

	// Step 1: Create Canonical Request
	canonicalURI := "/"
	canonicalQueryString := ""

	payloadBytes, _ := json.Marshal(payloadParams)
	payload := string(payloadBytes)
	canonicalHeaders := fmt.Sprintf("content-type:%s\nhost:%s\n", contentType, host)

	hashedPayload := sha256.Sum256([]byte(payload))
	canonicalRequest := fmt.Sprintf("%s\n%s\n%s\n%s\n%s\n%x", methodPost, canonicalURI, canonicalQueryString, canonicalHeaders, signedHeaders, hashedPayload)

	// Step 2: Create String to Sign
	credentialScope := fmt.Sprintf("%s/%s/tc3_request", date, service)
	hashedCanonicalRequest := sha256.Sum256([]byte(canonicalRequest))
	stringToSign := fmt.Sprintf("%s\n%d\n%s\n%x", "TC3-HMAC-SHA256", timestamp, credentialScope, hashedCanonicalRequest)

	// Step 3: Calculate Signature
	secretDate := s.sign([]byte("TC3"+secretKey), date)
	secretService := s.sign(secretDate, service)
	secretSigning := s.sign(secretService, "tc3_request")
	signature := hmac.New(sha256.New, secretSigning)
	signature.Write([]byte(stringToSign))
	signatureHex := hex.EncodeToString(signature.Sum(nil))

	// Step 4: Create Authorization Header
	authorization := fmt.Sprintf("TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s", secretID, credentialScope, signedHeaders, signatureHex)

	sougouAnswer := &rpc.SougouAnswerRaw{}
	err := s.httpClient.Do(ctx, map[string]string{
		"Authorization":  authorization,
		"Content-Type":   contentType,
		"Host":           host,
		"X-TC-Action":    action,
		"X-TC-Timestamp": cast.ToString(timestamp),
		"X-TC-Version":   version,
	}, nil, payloadParams, sougouAnswer)

	if err != nil {
		logger.Errorf(ctx, "SougouSearch failed: %v", err)
		return nil, err
	}

	displayInfos, pErr := sougouAnswer.ParseDisplayInfo()
	if pErr != nil {
		logger.Errorf(ctx, "SougouSearch ParseDisplayInfo failed: %v", pErr)
		return nil, pErr
	}

	var res []*rpc.OutSiteSearchRecallAnswerResult
	for _, answer := range displayInfos {
		// 解析时间字符串为 time.Time 对象
		publishedTime, timeErr := time.Parse("2006-01-02", answer.Date)
		if timeErr != nil {
			log.Errorf(ctx, "SougouSearch Time err => %s", timeErr.Error())
		}

		res = append(res, &rpc.OutSiteSearchRecallAnswerResult{
			Name:          answer.ContentTitle,
			Url:           answer.URL,
			Snippet:       answer.AbstractInfo,
			PublishedTime: publishedTime.UnixMilli(),
		})
	}

	// 由于搜狗搜索暂时还不能指定召回数量 所以这里先暂时做后limit限制
	return res[:zrecUtil.Min(int(topK), len(res))], nil
}

// sign 签名
func (s *SougouClientHttpImpl) sign(key []byte, msg string) []byte {
	h := hmac.New(sha256.New, key)
	h.Write([]byte(msg))
	return h.Sum(nil)
}

// generateMD5 生成MD5
func (s *SougouClientHttpImpl) generateMD5(pid, query, salt, token string) string {
	data := pid + query + salt + token
	hash := md5.Sum([]byte(data))
	return hex.EncodeToString(hash[:])
}
