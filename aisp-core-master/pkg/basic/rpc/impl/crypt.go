package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/Security-Platform/go-protos/crypt-go/gen-go/crypt_thrift"
	"git.in.zhihu.com/go/base/zae"
	"git.in.zhihu.com/go/box/tzone/client"
	apollo_config "git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const zhihaituApolloNamespace = "zhihaitu.properties"
const cryptSecretKey = "crypt_secret_key"

func init() {
	apollo_config.SubscribeToNamespaces(context.Background(), zhihaituApolloNamespace)
}

// CryptRpcImpl https://wiki.in.zhihu.com/pages/viewpage.action?pageId=183372650
type CryptRpcImpl struct {
	cryptService *crypt_thrift.CryptServiceClient
}

var DefaultCryptRpc rpc.CryptRpc

func init() {
	DefaultCryptRpc = newCryptImpl()
}

func newCryptImpl() *CryptRpcImpl {
	cryptClient := client.New("CryptService", client.Timeout(2000*time.Millisecond), client.TargetName("crypt-service"))
	return &CryptRpcImpl{
		cryptService: crypt_thrift.NewCryptServiceClient(cryptClient),
	}
}

func (c CryptRpcImpl) Encrypt(ctx context.Context, str string) (string, error) {
	response, err := c.cryptService.Encrypt(ctx, zae.App(), apollo_config.GetStringByNamespace(zhihaituApolloNamespace, cryptSecretKey, ""), str)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "encrypt error. str=%s", str)
		return "", err
	}

	return response.GetCipher(), nil
}

func (c CryptRpcImpl) Decrypt(ctx context.Context, str string) (string, error) {
	plainText, err := c.cryptService.Decrypt(ctx, zae.App(), apollo_config.GetStringByNamespace(zhihaituApolloNamespace, cryptSecretKey, ""), str)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "decrypt error. str=%s", str)
		return "", err
	}

	return plainText, nil
}
