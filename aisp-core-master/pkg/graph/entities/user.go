package entities

import (
	"strings"

	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type User struct {
	// 用户 id
	MemberId int64
	// 算子维度用户信息
	frameUser *data_frame.UserData[User]
	// meta 信息
	UserUserMeta *UserMeta
}

type UserMeta struct {
	// 用户名称
	username string
	// 用户领域
	bayesNames []string
	// 用户领域方向
	topicNames []string
	// 用户 Tags
	tags []string
	// 是否开启主动同步知识库
	isEnableOnsite bool
	// 是否允许通用知识库
	isEnableUniversal bool
	// 用户的标签信息
	tagInfo map[string]*tag_core.Tags
}

func (u *UserMeta) GetUserLastProvinceAndCity() (string, string) {
	provinceTagStr := ""
	cityTagStr := ""
	provinceTag, isTagOk := u.tagInfo["user_visit_province"]
	if isTagOk && provinceTag != nil && len(provinceTag.GetTagItems()) != 0 && len(provinceTag.GetTagItems()[0].GetTagValueInfos()) != 0 {
		provinceTagStr = provinceTag.GetTagItems()[0].GetTagValueInfos()[0].GetTagValue()
	}

	cityTag, isTagOk := u.tagInfo["user_visit_city"]
	if isTagOk && cityTag != nil && len(cityTag.GetTagItems()) != 0 && len(cityTag.GetTagItems()[0].GetTagValueInfos()) != 0 {
		cityTagStr = cityTag.GetTagItems()[0].GetTagValueInfos()[0].GetTagValue()
	}
	return provinceTagStr, cityTagStr
}

func (m *UserMeta) GetUserName() string {
	return m.username
}

func (m *UserMeta) SetUserName(username string) *UserMeta {
	m.username = username
	return m
}

func (m *UserMeta) GetBayesNames() []string {
	if m == nil {
		return []string{}
	}
	return m.bayesNames
}

func (m *UserMeta) SetBayesNames(bayesNames []string) *UserMeta {
	m.bayesNames = bayesNames
	return m
}

func (m *UserMeta) GetTopicNames() []string {
	return m.topicNames
}

func (m *UserMeta) SetTopicNames(topicNames []string) *UserMeta {
	m.topicNames = topicNames
	return m
}

func (m *UserMeta) GetFinalSkilledAnswer() string {
	if len(m.GetTopicNames()) > 0 {
		return strings.Join(m.GetTopicNames(), "、")
	}
	if len(m.GetBayesNames()) > 0 {
		return m.GetBayesNames()[0]
	}
	return ""
}

func (m *UserMeta) GetTags() []string {
	return m.tags
}

func (m *UserMeta) SetTags(tags []string) *UserMeta {
	m.tags = tags
	return m
}

func (m *UserMeta) GetTagInfo() map[string]*tag_core.Tags {
	return m.tagInfo
}

func (m *UserMeta) SetTagInfo(tagInfo map[string]*tag_core.Tags) *UserMeta {
	m.tagInfo = tagInfo
	return m
}

func NewUser(frameUser *data_frame.UserData[User]) *User {
	return &User{
		frameUser:    frameUser,
		UserUserMeta: &UserMeta{},
	}
}

func (u *User) UserMeta() *UserMeta {
	if u.UserUserMeta == nil {
		return &UserMeta{}
	}
	return u.UserUserMeta
}

func (u *User) SetUserMeta(userMeta *UserMeta) {
	u.UserUserMeta = userMeta
}

func (u *User) GetMemberId() int64 {
	if u == nil {
		return 0
	}
	return u.MemberId
}

func (u *User) SetMemberId(memberId int64) {
	u.MemberId = memberId
}

func (m *UserMeta) IsEnableOnsite() bool {
	return m.isEnableOnsite
}

func (m *UserMeta) SetIsEnableOnsite(isEnableOnsite bool) {
	m.isEnableOnsite = isEnableOnsite
}

func (m *UserMeta) IsEnableUniversal() bool {
	return m.isEnableUniversal
}

func (m *UserMeta) SetIsEnableUniversal(isEnableUniversal bool) {
	m.isEnableUniversal = isEnableUniversal
}

func (u *User) FrameUser() *data_frame.UserData[User] {
	return u.frameUser
}

func (u *User) SetFrameUser(frameUser *data_frame.UserData[User]) {
	u.frameUser = frameUser
}
