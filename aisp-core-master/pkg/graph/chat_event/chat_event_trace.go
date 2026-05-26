package chat_event

import (
	"encoding/json"
	"sort"

	"github.com/samber/lo"
)

type EventTrace struct {
	ParentEventId        string
	EventId              string
	EventType            ChatEventType
	EventState           ChatEventState
	BeginTimeMs          int64
	ProcessingDurationMs int64
	Trace                string
	Result               any
}

type eventTreeTrace struct {
	ParentEventId        string            `json:"-"`
	EventId              string            `json:"-"`
	EventTypeSource      ChatEventType     `json:"-"`
	EventType            string            `json:"eventType"`
	EventState           string            `json:"eventState"`
	BeginTimeMs          int64             `json:"beginTimeMs"`
	ProcessingDurationMs int64             `json:"processingDurationMs"`
	Trace                string            `json:"trace,omitempty"`
	Result               any               `json:"result,omitempty"`
	ChildEvents          []*eventTreeTrace `json:"childEvents,omitempty"`
}

// 将EventTrace列表转换为树结构
func buildEventTree(events []*EventTrace) *eventTreeTrace {
	if len(events) == 0 {
		return nil
	}

	// 创建映射表
	parentIds := make(map[string]int)
	nodeMap := make(map[string]*eventTreeTrace)
	var roots []*eventTreeTrace

	// 第一步：创建所有节点
	for _, event := range events {
		parentIds[event.ParentEventId] = 1
		node := &eventTreeTrace{
			ParentEventId:        event.ParentEventId,
			EventId:              event.EventId,
			EventType:            event.EventType.String(),
			EventTypeSource:      event.EventType,
			EventState:           event.EventState.String(),
			BeginTimeMs:          event.BeginTimeMs,
			ProcessingDurationMs: event.ProcessingDurationMs,
			Trace:                event.Trace,
			Result:               event.Result,
			ChildEvents:          make([]*eventTreeTrace, 0),
		}
		nodeMap[event.EventId] = node
	}

	// 补齐 root 节点
	for parentId := range parentIds {
		if _, isExist := nodeMap[parentId]; !isExist {
			node := &eventTreeTrace{
				ParentEventId: "",
				EventId:       parentId,
				EventType:     "Root",
				ChildEvents:   make([]*eventTreeTrace, 0),
			}
			nodeMap[parentId] = node
			roots = append(roots, node)
			break
		}
	}

	// 第二步：建立父子关系
	for _, event := range events {
		node := nodeMap[event.EventId]
		if event.ParentEventId == "" {
			// 根节点
			roots = append(roots, node)
		} else {
			// 查找父节点并添加子节点
			if parentNode, exists := nodeMap[event.ParentEventId]; exists {
				parentNode.ChildEvents = append(parentNode.ChildEvents, node)
			}
		}
	}

	// 第三步：对所有节点的子节点按EventType排序
	sortChildrenRecursively(roots)

	// 第四步：对根节点也按EventType排序
	sort.Slice(roots, func(i, j int) bool {
		return roots[i].EventType < roots[j].EventType
	})

	return lo.FirstOrEmpty(roots)
}

// 递归排序子节点
func sortChildrenRecursively(nodes []*eventTreeTrace) {
	for _, node := range nodes {
		if len(node.ChildEvents) > 0 {
			// 按EventType排序
			sort.Slice(node.ChildEvents, func(i, j int) bool {
				return node.ChildEvents[i].EventTypeSource < node.ChildEvents[j].EventTypeSource
			})

			// 递归排序子节点的子节点
			sortChildrenRecursively(node.ChildEvents)
		}
	}
}

func eventTreeToCompactJSON(events []*EventTrace) (string, error) {
	tree := buildEventTree(events)
	jsonData, err := json.Marshal(tree)
	if err != nil {
		return "", err
	}
	return string(jsonData), nil
}

func eventTreeToJSON(events []*EventTrace) (string, error) {
	tree := buildEventTree(events)
	jsonData, err := json.MarshalIndent(tree, "", "  ")
	if err != nil {
		return "", err
	}
	return string(jsonData), nil
}
