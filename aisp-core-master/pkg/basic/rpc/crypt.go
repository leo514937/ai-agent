package rpc

import "context"

type CryptRpc interface {
	Encrypt(ctx context.Context, str string) (string, error)
	Decrypt(ctx context.Context, str string) (string, error)
}
