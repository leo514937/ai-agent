package log

import (
	"context"
	"net/http"
	"strings"

	"git.in.zhihu.com/go/base/telemetry"
	"github.com/google/uuid"
)

type Transaction struct {
	*telemetry.Transaction
}

func (t *Transaction) End(ctx context.Context) {
	if t == nil {
		return
	}

	if t.Transaction == nil {
		return
	}

	t.Transaction.End(ctx, nil)
}

func StartTransaction(method string) (*Transaction, context.Context) {
	ctx := context.Background()

	traceID := strings.ReplaceAll(uuid.New().String(), "-", "")

	txn, ctx1, err := telemetry.StartTransaction(ctx, &telemetry.Transaction{
		System: telemetry.TransactionExec,
		Method: method,
	}, telemetry.ExtractHTTPHeaders(http.Header(map[string][]string{
		"x-b3-sampled": {"1"},
		"x-b3-traceid": {traceID},
		"x-b3-spanid":  {"1"},
	})))

	if err != nil {
		Error(ctx, "telemetry.StartTransaction", "err", err)
		return &Transaction{nil}, ctx
	}

	return &Transaction{txn}, ctx1
}
