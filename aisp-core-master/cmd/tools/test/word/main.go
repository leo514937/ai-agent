package main

import (
	"context"
	"flag"
	"fmt"
	"sync"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
)

func main() {
	waitGroup := sync.WaitGroup{}

	var (
		word      string
		queryType int
	)
	flag.StringVar(&word, "word", "hello world 1", "user input query")
	flag.IntVar(&queryType, "query_type", 3, "queryType")
	flag.Parse()
	fmt.Println("===================== 步骤1 获取词缓存")
	ctx := context.Background()
	wordId, err := word_service.DefaultWordMapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
		Word:     word,
		WordType: int32(queryType),
		SourceId: "",
	})
	if err != nil {
		fmt.Printf("ERROR 查询词Id 词:%s 异常 => %s \n", word, err)
		return
	}
	fmt.Printf("OK 查询词Id 正常 词:%s 词Id:%v \n", word, wordId)

	fmt.Println("===================== 步骤2 查看1000协程下 并发性能（实际测试单次请求大约 0.1ms）")
	waitGroup.Add(1000)
	// 记录开始时间
	startTime := time.Now()
	for i := 0; i < 1000; i++ {
		go func() {
			defer waitGroup.Done()
			_, err := word_service.DefaultWordMapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
				Word:     word,
				WordType: int32(queryType),
				SourceId: "",
			})
			if err != nil {
				fmt.Printf("ERROR 查询词Id 词:%s 异常 => %s \n", word, err)
			}
		}()
	}
	waitGroup.Wait()
	// 记录结束时间
	endTime := time.Now()
	fmt.Printf("并发查询词响应速度 正常 词:%s 词Id:%v 1000协程并发总耗时:%v \n", word, wordId, endTime.Sub(startTime))

	fmt.Println("===================== 步骤3 删除当前关键词（数据库逻辑删除+缓存清除）")

	isDelOk, delErr := word_service.DefaultWordMapperService.RemoveWordId(ctx, wordId, int32(queryType))
	if !isDelOk || delErr != nil {
		fmt.Printf("ERROR 删除词 异常 词:%s 词Id:%v isDelOk:%v Err:%v \n", word, wordId, isDelOk, delErr)
	} else {
		fmt.Printf("OK 删除词 正常 词:%s 词Id:%v isDelOk:%v \n", word, wordId, isDelOk)
	}

	fmt.Println("===================== 步骤4 验证缓存是否删除")
	wordId, err = word_service.DefaultWordMapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
		Word:     word,
		WordType: int32(queryType),
		SourceId: "",
	})
	if err != nil {
		fmt.Printf("ERROR 查询词Id 词:%s 异常 => %s \n", word, err)
	} else {
		fmt.Printf("OK 查询词Id 正常 词:%s 词Id:%v \n", word, wordId)
	}

	fmt.Println("===================== 步骤5 验证是否触发本地伪布隆")
	wordId, err = word_service.DefaultWordMapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
		Word:     word,
		WordType: int32(queryType),
		SourceId: "",
	})
	if err != nil {
		fmt.Printf("ERROR 查询词Id 词:%s 异常 => %s \n", word, err)
	} else {
		fmt.Printf("OK 查询词Id 正常 词:%s 词Id:%v \n", word, wordId)
	}

}
