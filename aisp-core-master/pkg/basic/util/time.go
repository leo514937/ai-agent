package util

import (
	"fmt"
	"time"

	"git.in.zhihu.com/go/utils"
)

func TimeUnixMilli() int64 {
	return utils.Now().UnixNano() / int64(time.Millisecond)
}

func TimeStamp2DateTime(timeStamp int64) string {
	tm := time.Unix(timeStamp, 0)
	return tm.Format("2006-01-02 15:04:05")
}

func TimeStamp2Date(timeStamp int64) string {
	tm := time.Unix(timeStamp, 0)
	return tm.Format("2006-01-02")
}

func Date2TimeStamp(date string) (int64, error) {
	tm, err := time.Parse("2006-01-02", date)
	if err != nil {
		fmt.Println("Error parsing time:", err)
		return 0, err
	}
	return tm.Unix(), nil
}

const (
	DateTimeFormat = "20060102150405"
)

func FormatTime2yyyyMMddHHmmss(t time.Time) string {
	return t.Format(DateTimeFormat)
}

func FormatTime2Datetime(t time.Time) string {
	return t.Format("2006-01-02 15:04:05.999")
}

func FormatTime2yyyyMMddTHHmmss(t time.Time) string {
	if t.Before(time.Date(1000, 0, 0, 0, 0, 0, 0, time.Local)) {
		return ""
	}
	return t.Format("2006-01-02T15:04:05")
}

func FormatSafeTime2yyyyMMddTHHmmss(t *time.Time) string {
	if t == nil || t.Before(time.Date(1100, 0, 0, 0, 0, 0, 0, time.Local)) {
		return ""
	}
	return t.Format("2006-01-02T15:04:05")
}

func GetNowDate() string {
	t := time.Now()
	return t.Format("2006年01月02日")
}

// StringDate2Time yyyyMMdd
func StringDate2Time(utc string) (time.Time, error) {
	parsedTime, err := time.ParseInLocation("20060102", utc, time.Local)
	if err != nil {
		fmt.Println("Error parsing time:", err)
		return time.Now(), err
	}
	return parsedTime, nil
}

// StringDate2TimeByFmt
func StringDate2TimeByFmt(dataStr string, fmt string) (time.Time, error) {
	parsedTime, err := time.ParseInLocation(fmt, dataStr, time.Local)
	if err != nil {
		return time.Now(), err
	}
	return parsedTime, nil
}

func Utc2Time(utc string) (time.Time, error) {
	parsedTime, err := time.ParseInLocation("2006-01-02T15:04:05.0000000", utc, time.Local)
	if err != nil {
		fmt.Println("Error parsing time:", err)
		return time.Now(), err
	}
	return parsedTime, nil
}

func PlusDate(delta int32) string {
	t := time.Now()
	t = t.AddDate(0, 0, int(delta))
	return t.Format("2006年01月02日")
}

func GetWeekDay(delta int32) string {
	t := time.Now()
	t = t.AddDate(0, 0, int(delta))
	return weekdays[t.Weekday()]
}

var weekdays = []string{"星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"}

func GetNowWeek() string {
	t := time.Now()
	return weekdays[t.Weekday()]
}

func GetNowTime() string {
	t := time.Now()
	return t.Format("15:04:05")
}

func GetNowYear() string {
	t := time.Now()
	return t.Format("2006")
}

func PlusYear(delta int32) string {
	t := time.Now()
	t = t.AddDate(int(delta), 0, 0)
	return t.Format("2006")
}

func IsMillisecond(ts int64) bool {
	return ts > 1e12
}
