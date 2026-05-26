package model

import "time"

type Tenant struct {
	ID          int64       `json:"id"`
	Owner       string      `json:"creator"`
	Name        string      `json:"name"`
	Description string      `json:"description"`
	State       TenantState `json:"state"`
	CreatedAt   time.Time   `json:"created_at"`
	UpdatedAt   time.Time   `json:"updated_at"`
}

type TenantState string

const (
	TenantStateNormal  TenantState = "NORMAL"
	TenantStateDeleted TenantState = "DELETED"
)
