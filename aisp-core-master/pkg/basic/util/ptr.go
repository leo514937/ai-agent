package util

func GetSafeString(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
