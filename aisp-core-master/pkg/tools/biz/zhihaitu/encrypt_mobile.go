package main

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
)

// 给数据库中encrypt_mobile字段插入值
func main() {

	ctx := context.Background()
	accounts, err := dao.DefaultOpenapiAccountDAO.ListAll(ctx)
	if err != nil {
		fmt.Print(err)
	}

	for index, account := range accounts {
		encryptMobile, err := impl.DefaultCryptRpc.Encrypt(ctx, account.Mobile)
		if err != nil {
			break
		}
		account.EncryptMobile = encryptMobile
		err = dao.DefaultOpenapiAccountDAO.UpdateEncryptMobile(ctx, account)
		if err != nil {
			fmt.Print(err)
			break
		}

		if index%10 == 0 {
			fmt.Printf("processing %d", index)
			time.Sleep(time.Second * 1)
		}
	}

	fmt.Printf("done")
}
