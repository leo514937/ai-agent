package main

import (
	"flag"
	"fmt"
	"io"
	"net/http"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_biz/aisp_core_translate"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/tools/api/grpc_service/translate-main/request"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

// 启动命令：
// server 端：make all;./bin/grpc-service
// client 端：go run cmd/tools/api/grpc_service/biz-main/main.go
func main() {
	var (
		host           string
		text           string
		memberID       int64
		batchSize      int
		sourceLanguage string
		targetLanguage string
	)
	flag.StringVar(&host, "host", "localhost:9999", "host name")
	flag.StringVar(&text, "text", "hello world", "user input query")
	flag.Int64Var(&memberID, "member_id", 246302179, "member id")
	flag.IntVar(&batchSize, "batch_size", 1, "协程批次")
	flag.StringVar(&sourceLanguage, "sl", "zh", "原语言")
	flag.StringVar(&targetLanguage, "tl", "en", "目标语言")
	flag.Parse()

	txn, ctx := log.StartTransaction("tools_api_grpc_biz_service")
	defer txn.End(ctx)

	contentProRpc := impl.NewContentProdRPCImpl()
	contentCoreRPC := impl.NewContentCoreRPCImpl()

	docs := []model.Content{
		//{ContentID: 253992565, ContentType: zaiContent.DocType_Article},
	}
	innerUrls := []string{
		//"https://zhuanlan.zhihu.com/p/24851728107",
		//"https://zhuanlan.zhihu.com/p/18671057346",
		//"https://zhuanlan.zhihu.com/p/10463276442",
	}
	outUrls := []string{
		//"https://www.opsli.com",
		//"https://www.baiyangseo.com/blog/1082.html",
	}

	// 分别从两个rum 表中获取引导词
	wg := safe_group.NewGroup("runCase")
	for i := 0; i < batchSize; i++ {
		wg.Go(func() error {
			//// 搜索召回接口
			//searchRequest := request.NewRecallSearchRequest(
			//	host,
			//	memberID,
			//	proto.KbRecallSearchType(searchType),
			//	[]proto.PersonalKnowledgeBaseType{proto.PersonalKnowledgeBaseType_PKB_RSS, proto.PersonalKnowledgeBaseType_PKB_FOLDER},
			//	[]proto.KbRecallSearchField{proto.KbRecallSearchField_RSF_TITLE},
			//)
			//searchRequest.DoRecallSearch(ctx, text)
			//
			//// 构建知识库索引接口
			//buildRequest := request.NewBuildKnowledgeBaseIndexRequest(
			//	host,
			//	memberID,
			//	11111111111111111,
			//	proto.DocType_EXTERNAL_WEBPAGE,
			//	11111111111111111,
			//	"test",
			//	proto.PersonalKnowledgeBaseType_PKB_FOLDER,
			//	proto.KbActionType_AT_INSERT,
			//)
			//buildRequest.DoBuildPersonalKnowledgeBaseIndex(ctx)

			// 翻译知乎html
			translateHTMLRequest := request.NewTranslateHTMLRequest(host)
			htmlContentArr := make([]string, 0)
			htmlContentArr = append(htmlContentArr, otherString)

			// 查询docs
			contentResultMap := contentCoreRPC.BatchGetContent(ctx, docs,
				base.ContentInfoFieldContentTitle,
				base.ContentInfoFieldContentBody)
			for _, content := range contentResultMap {
				if content.GetContentBody() == nil {
					continue
				}
				fmt.Println()
				fmt.Println(content.GetContentBody().GetBody())
				fmt.Println()
				htmlContentArr = append(htmlContentArr, content.GetContentBody().GetBody())
			}
			// 查询内容 url token
			contentProRes := contentProRpc.BatchCurlContentByUrl(ctx, innerUrls)
			for _, res := range contentProRes {
				htmlContentArr = append(htmlContentArr, res.GetContent())
			}
			// 查询站外内容
			for _, url := range outUrls {
				htmlContent := getOutUrlHTMLContent(url)
				if htmlContent != "" {
					htmlContentArr = append(htmlContentArr, htmlContent)
				}
			}

			for _, htmlContent := range htmlContentArr {
				translateHTMLRequest.DoTranslateHTML(ctx,
					htmlContent,
					proto.Language(proto.Language_value[sourceLanguage]),
					proto.Language(proto.Language_value[targetLanguage]))
				time.Sleep(100 * time.Millisecond)
			}
			return nil
		})
	}
	_ = wg.Wait()
}

func getOutUrlHTMLContent(url string) string {
	// 发送 GET 请求
	resp, err := http.Get(url)
	if err != nil {
		return ""
	}
	defer resp.Body.Close() // 确保关闭响应体

	// 检查 HTTP 响应状态码
	if resp.StatusCode != http.StatusOK {
		return ""
	}

	// 读取响应体内容
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return ""
	}

	// 将 HTML 文本输出
	return string(body)
}

var otherString = `
<p data-pid="sMNZKRKQ">1、附件文件</p><a data-draft-node="block" data-draft-type="file-link-card" href="https://pan.baidu.com/link/zhihu/7lh2zTuVhhiEMxc0JWZiJvx2Z4ayMENQQvZ1==" data-file-type="file" data-file-source="baidu" data-file-size="801" data-file-extension="txt">实训.txt</a><a href="https://www.jianshu.com/p/2a9fc9dd576e" data-draft-node="block" data-draft-type="link-card" data-image="v2-e691107df16746d4a9f3fe9496fd1848" data-image-width="601" data-image-height="601" data-image-size="l">java连接数据库基本操作（JDBC）</a><a href="https://zhuanlan.zhihu.com/p/20438863032" data-draft-node="block" data-draft-type="link-card" data-image="v2-0e6e1a71d9b24b194c20b5dce51a3593" data-image-width="1184" data-image-height="736" data-image-size="qhd">PaperAgent：一大波DeepSeek-R1开源复现来袭~</a><a href="http://www.news-sina.com.cn/" data-draft-node="block" data-draft-type="link-card" data-image="v2-05992d3434d3589b38a3a5431842d38f" data-image-width="128" data-image-height="128" data-image-size="l">国内新闻_新闻中心_新浪网</a><a href="https://www.bilibili.com/?spm_id_from=333.1073.0.0" data-draft-node="block" data-draft-type="link-card" data-image="v2-475f61f309834d0287a369e4f0957bd7" data-image-width="1920" data-image-height="180" data-image-size="qhd">哔哩哔哩 (゜-゜)つロ 干杯~-bilibili</a><a href="https://www.bilibili.com" data-draft-node="block" data-draft-type="link-card">哔哩哔哩 (゜-゜)つロ 干杯~-bilibili</a><p><br></p><p data-pid="hUWSSPO7">2、<i>部分</i>代码</p><code lang="text">try {
        Class.forName(className);//通过forName方法加载
        System.out.println("加载数据库驱动类已经成功！");
    } catch (ClassNotFoundException e) {
        // 捕获异常
        System.out.println("无法加载数据库驱动类！");
        e.printStackTrace();
    }</code><p data-pid="enBNXaWc">3、看到的文章<a href="https://www.jianshu.com/p/2a9fc9dd576e">java连接数据库基本操作（JDBC）</a>，可以简单看看</p><p data-pid="RL5P3wcx">4、python连接数据<sup data-text="看这里" data-url="https://blog.csdn.net/python03012/article/details/134809770" data-draft-node="inline" data-draft-type="reference" data-numero="1">[1]</sup></p><p data-pid="FgFEb7fi">5、百度<sup data-text="百度" data-url="http://www.baidu.com" data-draft-node="inline" data-draft-type="reference" data-numero="2">[2]</sup></p><p data-pid="1GOwd4pr">6、<b>其他（杂）</b></p><table data-draft-node="block" data-draft-type="table" data-size="normal" data-row-style="normal"><tbody><tr><th>科目</th><th>分数</th><th>备注</th></tr><tr><td>中国地理</td><td>98</td><td>非常OK了</td></tr><tr><td>语文</td><td>90</td><td>很OK了，但是还可以更OK一点，是吧</td></tr><tr><td>数学</td><td>80</td><td>快继续努力呀！！！！！</td></tr></tbody></table><video id="None" data-swfurl="" poster="https://picx.zhimg.com/v2-5a62ebc521f403fd7edd6a330e055d50.jpg?source=d16d100b" data-sourceurl="https://www.zhihu.com/zvideo/1564314803702767616" data-name="大风吹啊啊" data-video-id="" data-video-playable="true" data-lens-id="1564314802473807872" data-zvideo-id="1564314803702767616"></video><p data-pid="YxNXUP7Q">7、基础语法</p><p data-pid="1p5IWZUS"><b>变量声明与数据类型</b></p><ul><li data-pid="OLvu99T_"><b>基本数据类型</b>：包含 byte（1 字节）、short（2 字节）、int（4 字节）、long（8 字节）、float（4 字节）、double（8 字节）、char（2 字节）、boolean（1 位）</li><ul><li data-pid="Ks1qcyNU">例如：int num = 10。</li></ul><li data-pid="3p1N_d6R"><b>引用数据类型</b>：如类、接口、数组等。例如：String str = "Hello";</li></ul><p data-pid="gDDsLQDL">运算符</p><ul><ul><li data-pid="HLeMijBy"><b>算术运算符</b>：+、-、*、/、% 等。</li><li data-pid="ZVkcMqEs"><b>关系运算符</b>：&gt;、&lt;、&gt;=、&lt;=、==、!=。</li><li data-pid="-cOrY-uF"><b>逻辑运算符</b>：&amp;&amp;（逻辑与）、||（逻辑或）、!（逻辑非）。</li><li data-pid="yo3ojtzm"><b>位运算符</b>：&amp;（按位与）、|（按位或）、^（按位异或）、~（按位取反）等</li></ul></ul><p data-pid="rdztbzNr"><b>控制语句</b></p><ol><li data-pid="6Rpip6r5"><b>条件语句</b>：<code class="inline">if - else</code>、<code class="inline">switch - case</code>。</li><li data-pid="1QERG01A"><b>循环语句</b>：<code class="inline">for</code>、<code class="inline">while</code>、<code class="inline">do - while</code>。</li></ol><img src="v2-36a7449c82300ca281d9d9c22bdfdb88.png" data-caption="条件语句switch-case示例" data-size="normal" data-rawwidth="928" data-rawheight="482" data-watermark="original" data-original-src="v2-36a7449c82300ca281d9d9c22bdfdb88" data-watermark-src="v2-b01827f5dcb084560b5e94dcd3011038" data-private-watermark-src=""><blockquote data-pid="mh-7nwcQ">类：是对象的抽象描述，包含属性和方法。<br>对象：是类的实例。如：Person p = new Person(); <a href="http://p.name/">p.name</a> = "John"; p.age = 20; p.introduce(); </blockquote><p data-pid="kB5evx9g">下面这个图里是介绍的集合框架</p><img src="v2-59dc39e41881a3e3e2da4e8e24710d0d.png" data-caption="" data-size="normal" data-rawwidth="1190" data-rawheight="536" data-watermark="original" data-original-src="v2-59dc39e41881a3e3e2da4e8e24710d0d" data-watermark-src="v2-596ff280896212d06c92f5d14feff135" data-private-watermark-src=""><p></p><p></p>
`
