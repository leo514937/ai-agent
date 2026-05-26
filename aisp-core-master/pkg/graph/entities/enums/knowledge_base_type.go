package enums

import (
	"bytes"
	"text/template"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
)

var knowledgeBaseHandlerDict = map[KnowledgeBaseType]knowledgeBaseHandler{
	KnowledgeBaseTypeGlobal: {
		nameTemplateText: "{{.Name}}",
		descTemplateText: "{{.Desc}}",
		order:            1,
	},
	KnowledgeBaseTypeZhihu: {
		nameTemplateText: "{{.Name}}",
		descTemplateText: "{{.Desc}}",
		order:            2,
	},
	KnowledgeBaseTypePaper: {
		nameTemplateText: "{{.Name}}",
		descTemplateText: "{{.Desc}}",
		order:            3,
	},
	KnowledgeBaseTypePersonal: {
		nameTemplateText: "{{.Name}}",
		descTemplateText: "{{.Desc}}",
		order:            4,
	},
	KnowledgeBaseTypeHistoryDoc: {
		nameTemplateText: "用户历史对话文件",
		descTemplateText: "当前 session 内，用户历史对话过程曾引用过的文件",
		order:            5,
	},
	KnowledgeBaseTypeCurrDoc: {
		nameTemplateText: "当前引用内容",
		descTemplateText: "用户当前引用的文件内容",
		order:            6,
	},
	KnowledgeBaseTypeAuthor: {
		nameTemplateText: "{{.Name}}的知乎创作",
		descTemplateText: "知乎答主{{.Name}}在知乎社区创作的图文内容。\n{{.Desc}}",
		order:            7,
	},
	KnowledgeBaseTypePersonalFolder: {
		nameTemplateText: "{{.Name}}",
		descTemplateText: "用户在个人知识库下创建的名称为{{.Name}}的子知识库。\n{{.Desc}}",
		order:            8,
	},
	KnowledgeBaseTypeZhihuFavAll: {
		nameTemplateText: "知乎收藏夹",
		descTemplateText: "用户在知乎社区创建的收藏夹里的全部内容。\n{{.Desc}}",
		order:            9,
	},
	KnowledgeBaseTypeZhihuFav: {
		nameTemplateText: "知乎收藏夹: {{.Name}}",
		descTemplateText: "用户在知乎社区创建的名称为{{.Name}}的 收藏夹的内容。\n{{.Desc}}",
		order:            10,
	},
	KnowledgeBaseTypeRSSAll: {
		nameTemplateText: "用户全部的 RSS 订阅",
		descTemplateText: "用户在知乎直答订阅的全部 RSS 内容",
		order:            11,
	},
	KnowledgeBaseTypeRSS: {
		nameTemplateText: "用户订阅: {{.Name}}",
		descTemplateText: "用户在知乎直答订阅的名称为{{.Name}}的 RSS 内容。\n{{.Desc}}",
		order:            12,
	},
}

type knowledgeBaseHandler struct {
	nameTemplateText string
	descTemplateText string
	order            int
}

type KnowledgeBaseTemplateInput struct {
	Name string
	Desc string
}

type KnowledgeBase struct {
	name  string
	desc  string
	order int
}

func NewKnowledgeBase(knowledgeBaseType KnowledgeBaseType, name string, desc string) *KnowledgeBase {
	kb := &KnowledgeBase{
		name:  name,
		desc:  desc,
		order: 0,
	}

	handler, isExist := knowledgeBaseHandlerDict[knowledgeBaseType]
	if !isExist {
		return kb
	}

	kb.order = handler.order

	templateInput := &KnowledgeBaseTemplateInput{
		Name: name,
		Desc: desc,
	}

	// 创建一个模板对象并解析模板字符串
	nameBuffer := &bytes.Buffer{}
	nameTemplate, err := template.New("KnowledgeBaseNameTemplate").Parse(handler.nameTemplateText)
	if err != nil {
		return kb
	}
	err = nameTemplate.Execute(nameBuffer, templateInput)
	if err != nil {
		return kb
	}
	kb.name = nameBuffer.String()

	// 创建一个模板对象并解析模板字符串
	descBuffer := &bytes.Buffer{}
	descTemplate, err := template.New("KnowledgeBaseDescTemplate").Parse(handler.descTemplateText)
	if err != nil {
		return kb
	}
	err = descTemplate.Execute(descBuffer, templateInput)
	if err != nil {
		return kb
	}
	kb.desc = descBuffer.String()
	return kb
}

func (k *KnowledgeBase) GetFmtName() string {
	return k.name
}

func (k *KnowledgeBase) GetFmtDesc() string {
	return k.desc
}

func (k *KnowledgeBase) GetOrder() int {
	return k.order
}

type KnowledgeBaseType string

func (c KnowledgeBaseType) String() string {
	return string(c)
}

func ParseKnowledgeBaseType(s string) KnowledgeBaseType {
	return KnowledgeBaseType(s)
}

const (
	// KnowledgeBaseTypeGlobal 全网 done
	KnowledgeBaseTypeGlobal KnowledgeBaseType = "global"
	// KnowledgeBaseTypeZhihu 知乎 done
	KnowledgeBaseTypeZhihu KnowledgeBaseType = "zhihu"
	// KnowledgeBaseTypePaper 论文 done
	KnowledgeBaseTypePaper KnowledgeBaseType = "paper"
	// KnowledgeBaseTypePersonal 个人知识库 done
	KnowledgeBaseTypePersonal KnowledgeBaseType = "personal"
	// KnowledgeBaseTypeHistoryDoc 历史挂载 done
	KnowledgeBaseTypeHistoryDoc KnowledgeBaseType = "history_doc"
	// KnowledgeBaseTypeCurrDoc 当前挂载 done
	KnowledgeBaseTypeCurrDoc KnowledgeBaseType = "curr_doc"
	// KnowledgeBaseTypeAuthor 知乎答主 done
	KnowledgeBaseTypeAuthor KnowledgeBaseType = "zhihu_author"
	// KnowledgeBaseTypePersonalFolder 个人知识库文件夹 done
	KnowledgeBaseTypePersonalFolder KnowledgeBaseType = "personal_folder"
	// KnowledgeBaseTypeZhihuFavAll 知乎收藏夹(全部) done
	KnowledgeBaseTypeZhihuFavAll KnowledgeBaseType = "zhihu_fav_all"
	// KnowledgeBaseTypeZhihuFav 知乎收藏夹 done
	KnowledgeBaseTypeZhihuFav KnowledgeBaseType = "zhihu_fav"
	// KnowledgeBaseTypeRSSAll RSS订阅(全部) done
	KnowledgeBaseTypeRSSAll KnowledgeBaseType = "rss_all"
	// KnowledgeBaseTypeRSS RSS订阅 done
	KnowledgeBaseTypeRSS KnowledgeBaseType = "rss"
)

var KnowledgeBaseTypeNameMap = map[proto.KnowledgeBaseType]string{
	proto.KnowledgeBaseType_KBT_GLOBAL:                  "全网",
	proto.KnowledgeBaseType_KBT_ZHIHU:                   "知乎",
	proto.KnowledgeBaseType_KBT_PAPER:                   "学术",
	proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE: "个人知识库",
}

var KnowledgeBaseNameTypeMap = map[string]proto.KnowledgeBaseType{
	"全网":    proto.KnowledgeBaseType_KBT_GLOBAL,
	"知乎":    proto.KnowledgeBaseType_KBT_ZHIHU,
	"学术":    proto.KnowledgeBaseType_KBT_PAPER,
	"个人知识库": proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE,
}

var KnowledgeBaseTypeBizTypeMap = map[proto.KnowledgeBaseType]KnowledgeBaseType{
	proto.KnowledgeBaseType_KBT_GLOBAL:                  KnowledgeBaseTypeGlobal,
	proto.KnowledgeBaseType_KBT_ZHIHU:                   KnowledgeBaseTypeZhihu,
	proto.KnowledgeBaseType_KBT_PAPER:                   KnowledgeBaseTypePaper,
	proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE: KnowledgeBaseTypePersonal,
}
