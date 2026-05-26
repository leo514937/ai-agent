package redis

import (
	"errors"

	"git.in.zhihu.com/go/base/redis"
)

var (
	ErrNameNotFound = errors.New("name not found")
	ErrNil          = redis.Nil
)

type (
	Client    = redis.Client
	Pipeliner = redis.Pipeliner
	Z         = redis.Z
)
