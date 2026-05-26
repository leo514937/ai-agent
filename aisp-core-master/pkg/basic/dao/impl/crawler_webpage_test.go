package impl

import (
	"context"
	"testing"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

var webPages = []*model.CrawlerWebPage{
	{
		DocId:            1,
		DocType:          "type1",
		ObjectId:         "obj1",
		Title:            "Title 3",
		MetaUrl:          "http://example.com/1",
		Source:           "Source 1",
		SourceLevel:      1,
		Content:          "Content 3",
		Domain:           "example.com",
		PublishTime:      1633036800,
		IsCrawlerAllowed: 1,
		CrawlerTime:      1633123200,
		ExtraInfo:        "Extra info 1",
		CreatedAt:        time.Now(),
		UpdatedAt:        time.Now(),
	},
	{
		DocId:            2,
		DocType:          "type2",
		ObjectId:         "obj2",
		Title:            "Title 3",
		MetaUrl:          "http://example.com/2",
		Source:           "Source 2",
		SourceLevel:      2,
		Content:          "Content 2",
		Domain:           "example.com",
		PublishTime:      1633036801,
		IsCrawlerAllowed: 1,
		CrawlerTime:      1633123201,
		ExtraInfo:        "Extra info 2",
		CreatedAt:        time.Now(),
		UpdatedAt:        time.Now(),
	},
}

// go test /data/apps/aisp-core/pkg/basic/dao/impl -run TestCrawlerWebDaoImpl_BatchGet -v
// dlv test /data/apps/aisp-core/pkg/basic/dao/impl --headless --listen=:12316 --api-version=2 --accept-multiclient -- -test.run TestCrawlerWebDaoImpl_BatchGet
func TestCrawlerWebDaoImpl_BatchGet(t *testing.T) {

	type args struct {
		ctx  context.Context
		keys []*model.CrawlerWebPageKey
	}
	tests := []struct {
		name    string
		args    args
		want    []*model.CrawlerWebPage
		wantErr bool
	}{
		{
			name: "case1",
			args: args{
				ctx: context.TODO(),
				keys: []*model.CrawlerWebPageKey{
					{
						DocId:   1,
						DocType: "type1",
					},
					{
						DocId:   2,
						DocType: "type2",
					},
				},
			},
			want: webPages,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {

			got, err := DefaultCrawlerWebpageDao.BatchGet(tt.args.ctx, tt.args.keys)
			if (err != nil) != tt.wantErr {
				t.Errorf("BatchGet() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			t.Logf("keys=%v, got: %v", tt.args.keys, got)
			if len(got) != len(tt.want) {
				t.Errorf("BatchGet() got = %v, want %v", got, tt.want)
			}
		})
	}
}

// go test -run TestCrawlerWebDaoImpl_BatchInsert -v
// dlv test /data/apps/aisp-core/pkg/basic/dao/impl --headless --listen=:12316 --api-version=2 --accept-multiclient -- -test.run TestCrawlerWebDaoImpl_BatchInsert
func TestCrawlerWebDaoImpl_BatchInsert(t *testing.T) {

	type args struct {
		ctx  context.Context
		webs []*model.CrawlerWebPage
	}
	tests := []struct {
		name    string
		args    args
		wantErr bool
	}{
		{
			name: "case1",
			args: args{
				ctx:  context.TODO(),
				webs: webPages,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {

			if err := DefaultCrawlerWebpageDao.BatchUpsert(tt.args.ctx, tt.args.webs); (err != nil) != tt.wantErr {
				t.Errorf("BatchUpsert() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
