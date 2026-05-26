package mysql

import (
	"context"
	"database/sql"
	"errors"
)

var ErrNameNotFound = errors.New("name not found")

type Connection interface {
	Begin(ctx context.Context) Transaction
	WithTxn(ctx context.Context, f func() error) error

	Query(ctx context.Context, query string, args ...interface{}) (rows *sql.Rows, err error)
	QueryRow(ctx context.Context, query string, args ...interface{}) *sql.Row
	Exec(ctx context.Context, query string, args ...interface{}) (sql.Result, error)
	MustExec(ctx context.Context, query string, args ...interface{}) sql.Result
}

type Transaction interface {
	Rollback() error
	Commit() error

	Query(query string, args ...interface{}) (rows *sql.Rows, err error)
	QueryRow(query string, args ...interface{}) (rows *sql.Row)
	Exec(query string, args ...interface{}) (res sql.Result, err error)
	MustExec(query string, args ...interface{}) sql.Result
}

var NewConnection func(name string) Connection
