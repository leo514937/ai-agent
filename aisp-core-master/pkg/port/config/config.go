package config

import (
	"git.in.zhihu.com/go/cafe/config"
	"github.com/philchia/agollo/v4"
)

type (
	Client = agollo.Client
)

func GetClient() Client {
	return config.GetClient()
}
