package util

import "sync"

type SyncMap[K comparable, V any] struct {
	m    map[K]V
	lock sync.RWMutex
}

func NewSyncMap[K comparable, V any]() *SyncMap[K, V] {
	return &SyncMap[K, V]{
		m: make(map[K]V),
	}
}

func (m *SyncMap[K, V]) GetByIgnore(key K) V {
	m.lock.RLock()
	defer m.lock.RUnlock()
	v := m.m[key]
	return v
}

func (m *SyncMap[K, V]) Get(key K) (V, bool) {
	m.lock.RLock()
	defer m.lock.RUnlock()
	v, ok := m.m[key]
	return v, ok
}

func (m *SyncMap[K, V]) Set(key K, value V) {
	m.lock.Lock()
	defer m.lock.Unlock()
	m.m[key] = value
}

func (m *SyncMap[K, V]) Delete(key K) {
	m.lock.Lock()
	defer m.lock.Unlock()
	delete(m.m, key)
}

func (m *SyncMap[K, V]) Len() int {
	m.lock.RLock()
	defer m.lock.RUnlock()
	return len(m.m)
}

// Range 方法
func (m *SyncMap[K, V]) Range(f func(key K, value V) bool) {
	m.lock.RLock()
	defer m.lock.RUnlock()
	for k, v := range m.m {
		res := f(k, v)
		if !res {
			break
		}
	}
}

func (m *SyncMap[K, V]) Emplace(key K, factory func() (V, error)) (V, error) {
	m.lock.RLock()
	v, ok := m.m[key]
	m.lock.RUnlock()
	if ok {
		return v, nil
	}
	return m.emplaceSlow(key, factory)
}

func (m *SyncMap[K, V]) emplaceSlow(key K, factory func() (V, error)) (V, error) {
	m.lock.Lock()
	defer m.lock.Unlock()
	v, ok := m.m[key]
	if !ok {
		var err error
		v, err = factory()
		if err != nil {
			var zero V
			return zero, err
		}
		m.m[key] = v
	}
	return v, nil
}

// SyncSlice 是一个线程安全的泛型切片封装
type SyncSlice[T any] struct {
	mu    sync.RWMutex
	slice []T
}

func NewSyncSlice[T any]() *SyncSlice[T] {
	return &SyncSlice[T]{
		slice: make([]T, 0),
	}
}

// Append 向切片中添加一个元素
func (s *SyncSlice[T]) Append(value T) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.slice = append(s.slice, value)
}

// GetAll 获取切片中的所有元素
func (s *SyncSlice[T]) GetAll() []T {
	s.mu.RLock()
	defer s.mu.RUnlock()
	// 返回切片的副本以避免外部修改
	return append([]T(nil), s.slice...)
}

// Clear 清空切片
func (s *SyncSlice[T]) Clear() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.slice = s.slice[:0]
}

// Len 返回切片的长度
func (s *SyncSlice[T]) Len() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.slice)
}
