package util

import (
	"fmt"

	"github.com/spf13/cast"
	"github.com/xuri/excelize/v2"
)

func WriteCell(f *excelize.File, row int, column string, value interface{}) {
	err := f.SetCellValue("Sheet1", column+cast.ToString(row), value)
	if err != nil {
		fmt.Println(err)
		panic(err)
	}
}
