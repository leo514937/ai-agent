package logic

import (
	"context"
	"math/rand"
	"strconv"
	"time"

	apollo "git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/one-rpc-go/thrift-tag-core/tag_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetThemeLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetThemeLogic(name string, config map[string]string) *GetThemeLogic {
	g := &GetThemeLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	return g
}

func (g *GetThemeLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	userIDStr := strconv.FormatInt(request.UserID, 10)
	objType := tag_core_thrift.ObjType_User
	obj := &tag_core_thrift.ObjParam{
		ObjID:   &userIDStr,
		ObjType: &objType,
	}
	tagInfo, err := impl.DefaultTagCoreServiceImpl.GetTagContents(ctx, rpc.SceneCode_Ai_Daily, rpc.AppGroupCode_Ai_daily, obj)
	if err != nil {
		logger.Errorf(ctx, "[QueryThemeLogic] GetTagContents error: %v userID=%v", err, request.UserID)
		return nil
	}
	var themeData []model.ThemePair
	for _, info := range tagInfo {
		if info.GetTagInfo().TagCode == "text_theme_long_term" {
			for _, tagValue := range info.GetTagInfo().GetTagValues() {
				if tagValue.ThriftTagMeta != nil {
					themeData = append(themeData, model.ThemePair{
						ThemeID:   strconv.FormatInt(int64(tagValue.GetThriftTagMeta().GetMetaCode()), 10),
						ThemeName: tagValue.Value,
					})
				}
			}
		}
		if info.GetTagInfo().TagCode == "text_concept_word_short_term" {
			for _, tagValue := range info.GetTagInfo().GetTagValues() {
				playListData.HighDimensionalLabels = append(playListData.HighDimensionalLabels, tagValue.Value)
			}
		}

	}
	if len(themeData) > conf.MaxThemeLimit {
		themeData = themeData[:conf.MaxThemeLimit]
	}
	if len(themeData) > conf.MinThemeCountRandom {
		themeData = g.breakUpTheme(ctx, themeData)
	}
	playListData.ThemePairs = themeData
	logger.Infof(ctx, "GetTheme info.themeData=%v labels=%v", themeData, playListData.HighDimensionalLabels)
	return nil
}

func (g *GetThemeLogic) breakUpTheme(ctx context.Context, themeData []model.ThemePair) []model.ThemePair {
	// 打乱theme，每batch个选一个，batch内剩余追加到队尾
	batch := apollo.GetInt("theme_batch_select", conf.BatchSelectCountDefault)
	rand.NewSource(time.Now().UnixNano())
	newThemeData := make([]model.ThemePair, 0)
	otherThemeData := make([]model.ThemePair, 0)
	for i := 0; i < len(themeData); i += batch {
		end := i + batch
		if end > len(themeData) {
			end = len(themeData)
		}
		tempArr := themeData[i:end]
		randomIndex := rand.Intn(len(tempArr))
		newThemeData = append(newThemeData, tempArr[randomIndex])
		for j := 0; j < len(tempArr); j++ {
			if j == randomIndex {
				continue
			}
			otherThemeData = append(otherThemeData, tempArr[j]) // 先记录未被选取的theme
		}
	}
	newThemeData = append(newThemeData, otherThemeData...) // 未被选取的theme追加到队尾
	return newThemeData
}
