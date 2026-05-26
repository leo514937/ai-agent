package crawler_webpage

import "testing"

func TestIsUrlInBlackList(t *testing.T) {

	var tests = []string{
		"https://www.medsci.cn/topic/show",
		"https://www.medsci.cn/article/show_article.do;jsessionid=FE6EAB4CFB692B60DCF3D5CCA4D8D91E",
		"https://www.medsci.cn/guideline/show_article.do;jsessionid=B3549E3581DF84E00EB3196A20859CFF",
		"https://www.medsci.cn/user/subscrpition-modify",
		"https://www.youlai.cn/yyk/depthosp/99_9_1.html",
		"https://www.medsci.cn/department/details",
		"https://www.youlai.cn/ask/voicelist/9_63_0_1_8.html",
		"https://www.youlai.cn/dise/imagedetail/9_88496.html",
		"https://www.youlai.cn/dise/pz_Z_1.html",
		"https://www.familydoctor.com.cn/ask/doctor/9_0_0_2",
		"https://www.youlai.cn/dise/videolist/99_1.html",
		"https://www.youlai.cn/yyk/videolist_23570_1.html",
		"https://www.familydoctor.com.cn/ask/hot/deps_98",
		"https://www.familydoctor.com.cn/baby/myk/stage_9.html",
		"https://www.youlai.cn/yyk/hospindex/2098/registerlist_96141_0.html",
		"https://www.youlai.cn/yyk/hospindex/2059/registerlist_9_0.html",
		"https://www.familydoctor.com.cn/zhengxing/hot/g85",
		"https://www.medsci.cn/cn/submit.do",
		"https://www.familydoctor.com.cn/yinshi/sck/style_6_0_0_0_1.html",
		"https://www.familydoctor.com.cn/error/index.html",
		"https://www.youlai.cn/video/pcplayup/1/997.html",
		"https://www.familydoctor.com.cn/ask/comment/q/38749462",
		"https://www.youlai.cn/video/pcplayup/2/998.html",
		"https://www.medsci.cn/eda/subject/98-1",
		"https://www.medsci.cn/eda/detail/fec0188415",
		"https://www.medsci.cn/case/send",
		"https://www.familydoctor.com.cn/ask/jbk/d8354",
		"https://www.familydoctor.com.cn/ask/did/107/8",
		"https://www.familydoctor.com.cn/buyunbuyu/by/201206/988786105925.html",
		"https://www.youlai.cn/toutiao/page_7.html",
		"https://www.medsci.cn/meeting/show.do",
		"https://www.youlai.cn/yyk/deptindex/99.html",
		"https://www.youlai.cn/kp/9_91_1.html",
		"https://www.medsci.cn/form/detail.do",
		"https://www.dayi.org.cn/video_list/16/99",
		"https://www.medsci.cn/link/sci_redirect",
		"https://www.familydoctor.com.cn/ask/did/123/6",
		"https://www.medsci.cn/service/tree_list.do",
		"https://www.medsci.cn/live/ffb3d7a4499183",
		"https://www.youlai.cn/super/dise_93_9.html",
		"https://www.familydoctor.com.cn/yinshi//hot/49109",
		"https://www.familydoctor.com.cn/yangsheng//hot/39503",
	}

	for _, tt := range tests {
		t.Run("", func(t *testing.T) {
			if got := DefaultCrawlerWebpageService.IsUrlInBlackList(tt); got != true {
				t.Errorf("tt not int blacklist. url: %s", tt)
			}
		})
	}
}
