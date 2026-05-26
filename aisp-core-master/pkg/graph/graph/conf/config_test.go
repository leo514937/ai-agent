package conf

import (
	"reflect"
	"testing"
)

func TestCreateFaqMatchTypeCombinations(t *testing.T) {
	type args struct {
		faqMatchTypes []FaqMatchType
	}
	tests := []struct {
		name string
		args args
		want []int
	}{
		{
			name: "zero_param",
			args: args{faqMatchTypes: []FaqMatchType{}},
			want: []int{},
		},
		{
			name: "one_param",
			args: args{faqMatchTypes: []FaqMatchType{FaqMatchTypeFullMatch}},
			want: []int{4, 6, 12, 14, 20, 22, 28, 30},
		},
		{
			name: "two_param",
			args: args{faqMatchTypes: []FaqMatchType{FaqMatchTypeFullMatch, FaqMatchTypeEmbeddingSimilarity}},
			want: []int{2, 4, 6, 10, 12, 14, 18, 20, 22, 26, 28, 30},
		},
		{
			name: "four_param",
			args: args{faqMatchTypes: []FaqMatchType{FaqMatchTypeEmbeddingSimilarity, FaqMatchTypeFullMatch, FaqMatchTypeKeywordMatchAll, FaqMatchTypeKeywordMatchAny}},
			want: []int{2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := CreateFaqMatchTypeCombinations(tt.args.faqMatchTypes); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("CreateFaqMatchTypeCombinations() = %v, want %v", got, tt.want)
			}
		})
	}
}
