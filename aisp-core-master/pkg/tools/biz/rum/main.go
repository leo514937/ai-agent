package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
)

func main() {
	ctx := context.Background()
	initData(ctx)
}

// 初始化rum用到的hive表
func initData(ctx context.Context) {
	hiveClient := resource.NewHiveClient()
	defer hiveClient.Close()
	sql := fmt.Sprintf("INSERT overwrite TABLE aisp.personal_kb_content_1024d partition (p_date = '2025-07-29')\nselect\n `id`,\n`hash`,\n`status`,\n`created_at`,\n`updated_at`,\n`raw`,\n`embedding`,\n117223006 as `member_id`,\n'673230591' as `content_id`,\n'Answer' as `doc_type`,\n'1' as `knowledge_base_id`,\n'' as `knowledge_base_name`,\n'' as `knowledge_base_type`,\n'' as `extra`,\n'' as extra2\n from ai.arxiv_title_bge_1024d\nwhere\n  p_date='2025-07-25' limit 1")

	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.strict.checks.large.query=false")
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, sql)
	if cursor.Err != nil {
		fmt.Println("Err:", cursor.Err)
		return
	}
	cursor.Close()
}
