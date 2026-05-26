package model

type App struct {
	Name             string `json:"name"`
	OwnerEmail       string `json:"owner_email"`
	OwnerBizLineName string `json:"owner_biz_line_name"`
}
