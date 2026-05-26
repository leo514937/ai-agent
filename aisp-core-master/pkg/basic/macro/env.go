package macro

import (
	"os"
	"strings"

	"github.com/samber/lo"
)

var Debug = lo.Contains([]string{"1", "true", "t", "y", "yes"}, strings.ToLower(os.Getenv("DEBUG")))
