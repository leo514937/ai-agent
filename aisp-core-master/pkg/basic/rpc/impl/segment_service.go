package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/thrift-go/zai_pb_thrift"
	"git.in.zhihu.com/thrift-go/zai_pb_thrift/segment"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
)

type SegmentImpl struct {
	segmentClient *zai_pb_thrift.SegmentServiceClient
}

var DefaultSegmentImpl rpc.SegmentRPC

func init() {
	DefaultSegmentImpl = NewSegmentImpl()
}
func NewSegmentImpl() *SegmentImpl {
	segmentClient := tzone.NewClient(
		"SegmentService",
		tzone.TargetName("zai-lac-for-zai"),
		tzone.Timeout(2000*time.Millisecond),
	)

	return &SegmentImpl{
		segmentClient: zai_pb_thrift.NewSegmentServiceClient(segmentClient),
	}
}

func (s *SegmentImpl) Segment(ctx context.Context, text string, stopWordType string, removePuncts bool, removeEmoji bool, mergeCoarse bool) *content.Segment {
	if stopWordType == "" {
		stopWordType = "None"
	}

	request := &segment.SegmentRequest{
		Content:      &text,
		FieldType:    "Default",
		StopWordType: stopWordType,
		RemovePuncts: removePuncts,
		RemoveEmoji:  removeEmoji,
		MergeCoarse:  mergeCoarse,
	}

	result := &content.Segment{}
	runFunc := func(ctx context.Context) error {
		resp, err := s.segmentClient.Segment(ctx, request)
		if err != nil {
			return err
		}

		if resp != nil && resp.GetSegment() != nil {
			_ = util.ProtoUnmarshalMerge(result, resp.GetSegment())
		}

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return result
}

func (s *SegmentImpl) Clean(ctx context.Context, text string) string {
	if text == "" {
		return ""
	}

	var result string

	runFunc := func(ctx context.Context) error {
		request := &segment.CleanRequest{
			Content:                    &text,
			Transfer2SimplifiedChinese: true,
			RemoveHTML:                 true,
			Lower:                      false,
			Trim:                       true,
			ReplaceInvisible:           true,
			ReplaceMultiSpace:          true,
			KeepCaption:                true,
			RemoveEmoji:                true,
			ReplaceURL:                 true,
		}
		resp, err := s.segmentClient.Clean(ctx, request)
		if err != nil || resp == nil {
			return err
		}

		result = resp.GetCleaned()
		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return result
}

var _ rpc.SegmentRPC = (*SegmentImpl)(nil)
