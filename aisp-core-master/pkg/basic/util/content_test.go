package util

import (
	"context"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestContentFilterHtml(t *testing.T) {
	ctx := context.Background()

	content := "<div class=\"content-article\"> <div id=\"ArticleColumnTag\"></div><h1>英格兰联赛是本届欧洲杯参赛球员最多的联赛</h1><span>2024-06-11 01:39</span><span>发布于</span><span>懂球帝官方账号</span></p></div>"
	content = ContentFilterScripts(ctx, content)
	res, err := ContentFilterHtml(ctx, content)
	res = strings.TrimSpace(res)
	assert.Equal(t, "英格兰联赛是本届欧洲杯参赛球员最多的联赛2024-06-11 01:39发布于懂球帝官方账号", res)
	assert.Nil(t, err)

	content2 := "<section class=\"f_right detail_article_content p_t_20\"> <script> var playList = []; scale = window.innerWidth / 750 <= 1 ? window.innerWidth / 750 : 1; $(\"#player-video-wrapper\").css(\"width\",'100%'); $(\"#player-video-wrapper\").css(\"height\",\"100%\"); var plyrSvg = '<svg width=\"100%\" height=\"100%\" viewBox=\"0 0 348 348\" version=\"1.1\" xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\" xml:space=\"preserve\" xmlns:serif=\"http://www.serif.com/\" style=\"fill-rule:evenodd;clip-rule:evenodd;stroke-linejoin:round;stroke-miterlimit:1.41421;\"><g id=\"白色按钮\"></g></svg>' $(\"#player-video-wrapper\").attr( \"poster\",'https://imgs.rednet.cn/data/24/IMAGE_TENANT_LIB/IMAGE/5350/2024/5/21/9012ff0d8e3c4112975683b817fe0109.jpg'); $(\"#player-video-wrapper\").append($(\"<source src='http://1400289574.vod2.myqcloud.com/d4450852vodtranscq1400289574/9d199e7f1253642697351603425/v.f30.mp4' type='video/mp4'><\\/source>\")); </script> <script> var coverPlayer = new Plyr('#player-video-wrapper',{controls:['play-large', 'play', 'progress', 'current-time', 'volume', 'fullscreen']}); coverPlayer.on('ready', function(event) { $(\".plyr__control--overlaid svg\").remove(); $(\".plyr__control--overlaid .plyr__sr-only\").before(plyrSvg) }); playList.push(coverPlayer); coverPlayer.on('play', function() { for(var j= 0 , k= playList.length; j < k; j++){ if(!(coverPlayer == playList[j])){ playList[j].pause(); } } }); /*全屏事件*/ coverPlayer.on('enterfullscreen', function(event) { var element = event.detail.plyr.media; $(element).css(\"width\",\"100%\"); $(element).css(\"height\",\"100%\"); console.log(event) }); /*退出全屏事件*/ coverPlayer.on('exitfullscreen', function(event) { var element = event.detail.plyr.media; var scale = window.innerWidth / 700 <= 1 ? window.innerWidth / 700 : 1; $(element).css(\"width\",640*scale +\"px\"); $(element).css(\"height\",(640*9/16)*scale + \"px\"); }); </script> <ct></ct> </section>"
	content2 = ContentFilterScripts(ctx, content2)
	res2, err2 := ContentFilterHtml(ctx, content2)
	res2 = strings.TrimSpace(res2)
	assert.Equal(t, "", res2)
	assert.Nil(t, err2)

	content3 := "<!DOCTYPE html> <html> <body><p>这是一段文本</p><script>alert('XSS1');</script><p>这是一段文本</p></body></html>"
	content3 = ContentFilterScripts(ctx, content3)
	res3, err3 := ContentFilterHtml(ctx, content3)
	res3 = strings.TrimSpace(res3)
	assert.Equal(t, "这是一段文本这是一段文本", res3)
	assert.Nil(t, err3)
}
