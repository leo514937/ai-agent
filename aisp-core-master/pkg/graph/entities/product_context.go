package entities

type ProductContext interface {
	GetProductName() string
}

type ProductResultItem interface {
	IsProductResultItem() // 空函数，只用于继承
}

type MockProductContext struct {
	name string
}

func NewMockProductContext(name string) *MockProductContext {
	return &MockProductContext{name: name}
}

var _ ProductContext = (*MockProductContext)(nil) // 检测是否实现全部方法

func (p *MockProductContext) GetProductName() string {
	return p.name
}
