package util

import (
	"bytes"
	"strings"

	"golang.org/x/net/html"
)

// HTMLWalk walks the HTML tree of s and calls f for each node.
func HTMLWalk(s string, f func(parent, node *html.Node) bool) []*html.Node {
	doc, err := html.ParseFragment(strings.NewReader(s), nil)
	if err != nil {
		panic(err)
	}
	if len(doc) == 0 {
		return nil
	}
	var df func(*html.Node, *html.Node)
	df = func(parent, n *html.Node) {
		if n.Type == html.ElementNode {
			if !f(parent, n) {
				return
			}
		}
		for c := n.FirstChild; c != nil; c = c.NextSibling {
			df(n, c)
		}
	}
	dummyNode := &html.Node{
		FirstChild: doc[0],
		LastChild:  doc[len(doc)-1],
	}
	for i, n := range doc {
		if i > 0 {
			doc[i-1].NextSibling = n
			n.PrevSibling = doc[i-1]
		} else {
			n.PrevSibling = nil
		}
		if i < len(doc)-1 {
			n.NextSibling = doc[i+1]
			doc[i+1].PrevSibling = n
		} else {
			n.NextSibling = nil
		}
		n.Parent = dummyNode
	}
	for _, n := range doc {
		df(dummyNode, n)
	}
	nodes := []*html.Node{}
	for c := dummyNode.FirstChild; c != nil; c = c.NextSibling {
		nodes = append(nodes, c)
	}
	return nodes
}

func HTMLFilter(s string, f func(node *html.Node) bool) string {
	nodes := HTMLWalk(s, func(parent, node *html.Node) bool {
		if !f(node) {
			node.Parent = nil
			if node.PrevSibling != nil {
				node.PrevSibling.NextSibling = node.NextSibling
			} else {
				parent.FirstChild = node.NextSibling
			}
			if node.NextSibling != nil {
				node.NextSibling.PrevSibling = node.PrevSibling
			} else {
				parent.LastChild = node.PrevSibling
			}
			return false
		}
		return true
	})
	buf := &bytes.Buffer{}
	for _, node := range nodes {
		_ = html.Render(buf, node)
	}
	return buf.String()
}

func NodeToHtml(node *html.Node) string {
	buf := &bytes.Buffer{}
	_ = html.Render(buf, node)
	return buf.String()
}
