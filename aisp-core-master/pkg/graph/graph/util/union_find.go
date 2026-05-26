package util

type UnionFind struct {
	parent map[int]int
}

func NewUnionFind() *UnionFind {
	return &UnionFind{
		parent: make(map[int]int),
	}
}

func (uf *UnionFind) Find(x int) int {
	if _, found := uf.parent[x]; !found {
		uf.parent[x] = x
	} else if uf.parent[x] != x {
		uf.parent[x] = uf.Find(uf.parent[x])
	}
	return uf.parent[x]
}

func (uf *UnionFind) Union(x, y int) {
	rootX := uf.Find(x)
	rootY := uf.Find(y)
	if rootX != rootY {
		uf.parent[rootX] = rootY
	}
}
