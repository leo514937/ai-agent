package module

type HotEventKafkaMsg struct {
	HotEvent HotEvent `json:"hot_event"`
	OpType   string   `json:"op_type"`
	Question []int64  `json:"question"`
}

type HotEvent struct {
	Id           int64      `json:"id"`
	HotSpotName  string     `json:"hot_spot_name"`
	RawEventName string     `json:"raw_event_name"`
	HotLevel     string     `json:"hot_level"`
	IsAbandon    StatusCode `json:"is_abandon"`
	IsOperation  StatusCode `json:"is_operation"`
	IsFollowed   StatusCode `json:"is_followed"`
}

type StatusCode int

const (
	Yes StatusCode = 1
	No  StatusCode = 2
)
