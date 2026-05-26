package util

import (
	"testing"

	"github.com/stretchr/objx"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

// fixme:for go vendor import stretchr
func TestSomething(t *testing.T) {
	assert.Equal(t, 123, 123, "they should be equal")

	jsonString := "{\"a\":1}"
	_, _ = objx.FromJSON(jsonString)

	_ = mock.Anything
}
