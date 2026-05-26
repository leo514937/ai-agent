package entities

import (
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// RefMountData 挂载数据
type RefMountData struct {
	RefDatas []*proto.ReferenceMount
}

func NewRefMountData(refDatas []*proto.ReferenceMount) *RefMountData {
	return &RefMountData{
		RefDatas: refDatas,
	}
}

func (r *RefMountData) PutRefData(ref *proto.ReferenceMount) {
	r.RefDatas = append(r.RefDatas, ref)
}

// GetMountLength 获取挂载个数
func (r *RefMountData) GetMountLength() int {
	return len(r.RefDatas)
}

// GetMountLength 获取挂载个数
func (r *RefMountData) GetMountNonTextLength() int {
	return len(lo.Filter(r.RefDatas, func(item *proto.ReferenceMount, index int) bool {
		return item != nil && item.GetMountText().GetText() == ""
	}))
}

// IsMountPureDoc 是否挂载纯文档
func (r *RefMountData) IsMountPureDoc() bool {
	return len(r.GetMountDocs()) == r.GetMountLength() && r.GetMountLength() > 0
}

// GetMountBases 获取挂载的个人知识库
func (r *RefMountData) GetMountBases() []*proto.PersonalKnowledgeBase {
	filterData := lo.Filter(r.RefDatas, func(refData *proto.ReferenceMount, _ int) bool {
		return refData.GetMountBase().GetKnowledgeBaseType() != proto.PersonalKnowledgeBaseType_PKB_UNDEFINED ||
			refData.GetMountBase().GetVisibility() != proto.KnowledgeBaseVisibility_UNDEFINED_VISIBILITY
	})
	uniqData := lo.UniqBy(filterData, func(item *proto.ReferenceMount) string {
		return fmt.Sprintf("%d-%d-%d", item.GetMountBase().GetKnowledgeBaseType(), item.GetMountBase().GetKnowledgeBaseId(), item.GetMountBase().GetVisibility())
	})
	return lo.Map(uniqData, func(item *proto.ReferenceMount, index int) *proto.PersonalKnowledgeBase {
		return item.GetMountBase()
	})
}

func (r *RefMountData) HasFavUniversalBase() bool {
	_, isHit := lo.Find(r.GetMountBases(), func(item *proto.PersonalKnowledgeBase) bool {
		return item.GetKnowledgeBaseId() == 0 && item.GetKnowledgeBaseType() == proto.PersonalKnowledgeBaseType_PKB_FAV
	})
	return isHit
}

// GetMountDocs 获取挂载的文档
func (r *RefMountData) GetMountDocs() []*proto.DocIdentity {
	docTypes := []proto.DocType{proto.DocType_ANSWER, proto.DocType_ARTICLE, proto.DocType_PAPER,
		proto.DocType_ZHI_DA_USER_UPLOAD, proto.DocType_EXTERNAL_WEBPAGE, proto.DocType_INTERNAL_DOC, proto.DocType_AISP_USER_UPLOAD}
	filterData := lo.Filter(r.RefDatas, func(refData *proto.ReferenceMount, _ int) bool {
		return refData.GetMountDoc().GetDocId() != 0 && lo.Contains(docTypes, refData.GetMountDoc().GetDocType())
	})
	uniqData := lo.UniqBy(filterData, func(item *proto.ReferenceMount) string {
		return item.GetMountDoc().GetDocType().String() + "-" + cast.ToString(item.GetMountDoc().GetDocId())
	})
	return lo.Map(uniqData, func(item *proto.ReferenceMount, index int) *proto.DocIdentity {
		return item.GetMountDoc()
	})
}

// GetMountMembers 获取挂载的用户数据
func (r *RefMountData) GetMountMembers() []int64 {
	filterData := lo.Filter(r.RefDatas, func(refData *proto.ReferenceMount, _ int) bool {
		return refData.GetMountDoc().GetDocId() != 0 && refData.GetMountDoc().GetDocType() == proto.DocType_MEMBER
	})
	uniqData := lo.UniqBy(filterData, func(item *proto.ReferenceMount) string {
		return item.GetMountDoc().GetDocType().String() + "-" + cast.ToString(item.GetMountDoc().GetDocId())
	})
	return lo.Map(uniqData, func(item *proto.ReferenceMount, index int) int64 {
		return item.GetMountDoc().GetDocId()
	})
}

// GetMountTexts 获取挂载的文本
func (r *RefMountData) GetMountTexts() []string {
	filterData := lo.Filter(r.RefDatas, func(refData *proto.ReferenceMount, _ int) bool {
		return refData.GetMountText().GetText() != ""
	})
	return lo.Map(filterData, func(item *proto.ReferenceMount, index int) string {
		return item.GetMountText().GetText()
	})
}
