package util

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestAbstractMake(t *testing.T) {
	var runCount = 0
	getMap := Make(func() interface{} {
		result := make(map[string]float64)
		result["alpha"] = 3.0
		result["bravo"] = 4.0
		result["charlie"] = 5.0
		runCount++
		return result
	})
	idfMap := getMap().(map[string]float64)
	assert.InDelta(t, 5.0, idfMap["charlie"], 0.01)
	idfMap2 := getMap().(map[string]float64)
	assert.InDeltaMapValues(t, idfMap, idfMap2, 0.01)
	assert.EqualValues(t, idfMap, idfMap2)
	assert.Equal(t, 1, runCount)
}
