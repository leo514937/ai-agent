package errors

import "fmt"

var ErrModelNotFound = fmt.Errorf("model not found")
var ErrInvalidArgument = fmt.Errorf("invalid argument")
