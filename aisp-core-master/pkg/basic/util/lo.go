package util

func List[I any](a ...I) []I {
	return a
}

func SafeNew[I any](newer func() (I, error)) I {
	defer func() {
		recover()
	}()
	i, _ := newer()
	return i
}

type DefaultMap[K comparable, V any] struct {
	m           map[K]V
	constructor func() V
}

func NewDefaultMap[K comparable, V any](constructor func() V) *DefaultMap[K, V] {
	return &DefaultMap[K, V]{
		m:           make(map[K]V),
		constructor: constructor,
	}
}

func (m *DefaultMap[K, V]) Get(k K) V {
	v, ok := m.m[k]
	if !ok {
		v = m.constructor()
		m.m[k] = v
	}
	return v
}

func (m *DefaultMap[K, V]) Set(k K, v V) {
	m.m[k] = v
}

func (m *DefaultMap[K, V]) Delete(k K) {
	delete(m.m, k)
}

func (m *DefaultMap[K, V]) ToMap() map[K]V {
	return m.m
}

func (m *DefaultMap[K, V]) FromMap(mm map[K]V) *DefaultMap[K, V] {
	m.m = mm
	return m
}

type Progress[V any] struct {
	V V
	E error
}
