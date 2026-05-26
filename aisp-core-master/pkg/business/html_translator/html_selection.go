package html_translator

// 知乎卡片链接class 其中 ad-link-card 和 mcn-link-card 需要忽略
/**
const CardTypeLinkCard = "link-card"
const CardTypeMcnLinkCard = "mcn-link-card"
const CardTypeMetaLink = "metalink"
const CardTypeKmSkuCard = "km-sku-card"
const CardTypeFileLinkCard = "file-link-card"
const CardTypeEduCard = "edu-card"
const CardTypeAdLinkCard = "ad-link-card"
const CardTypeFeeLinkCard = "fee-link-card"
const CardTypeVideoLinkCard = "video-link-card"
*/

var DefaultNotTranslatedSelections = []string{
	// 忽略 @用户名
	".UserLink-link",
	".member_mention",
	// 忽略 商业内容卡片
	"a[data-draft-type='ad-link-card']",
	"a[data-draft-type='mcn-link-card']",
	// 国内ICP、网安备案（后续还需补充大模型、医药、旅游等资质备案）
	"a[href*='beian.miit.gov.cn'],a[href*='beian.mps.gov.cn'],a[href*='www.beian.gov.cn']",
	// 公式类
	".ztext-math",
}
