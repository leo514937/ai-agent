package util

import "strings"

func GetFirstIp(ip string) string {
	if strings.Contains(ip, ",") {
		return strings.TrimSpace(strings.Split(ip, ",")[0])
	}
	return ip
}
