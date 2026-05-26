// Package utils provides utility functions for text processing
package util

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// Match represents a matched number with unit in text
type Match struct {
	OriginalText string
	StartPos     int
	EndPos       int
}

var (
	// Pre-compiled special format patterns
	specialFormatPatterns = []*regexp.Regexp{
		// Resolution format
		regexp.MustCompile(`\d+\s*[xX×]\s*\d+`),
		// Ratio format
		regexp.MustCompile(`\d+\s*[:：]\s*\d+`),
		// Date time patterns
		regexp.MustCompile(`\d{4}[-/\.年]\d{1,2}[-/\.月]\d{1,2}[日号]?\s*\d{1,2}[:：]\d{1,2}([:：]\d{1,2})?`),
		regexp.MustCompile(`\d{4}[-/\.年]\d{1,2}[-/\.月]\d{1,2}[日号]?\s*\d{1,2}时\d{1,2}分(\d{1,2}秒)?`),
		regexp.MustCompile(`\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4}\s*\d{1,2}[:：]\d{1,2}([:：]\d{1,2})?`),
		regexp.MustCompile(`\d{1,2}月\d{1,2}[日号]\s*\d{1,2}[:：]\d{1,2}([:：]\d{1,2})?`),
		regexp.MustCompile(`\d{1,2}月\d{1,2}[日号]\s*\d{1,2}时\d{1,2}分(\d{1,2}秒)?`),
		// Compound unit patterns
		regexp.MustCompile(`\d+(?:\.\d+)?元\/(?:个|只|件|千克|公斤|kg|KG|斤|克|g|吨|t|米|m|厘米|cm|毫米|mm|千米|km|公里)`),
		regexp.MustCompile(`(?:￥|\$|€|£|¥)?\d+(?:\.\d+)?\/(?:个|只|件|千克|公斤|kg|KG|斤|克|g|吨|t|米|m|厘米|cm|毫米|mm|千米|km|公里)`),
		regexp.MustCompile(`\d+(?:\.\d+)?升\/\d+(?:\.\d+)?(?:千米|公里|km)`),
		regexp.MustCompile(`\d+(?:\.\d+)?[Ll]\/\d+(?:\.\d+)?[Kk]m`),
		regexp.MustCompile(`\d+(?:\.\d+)?(?:米|m|公里|km|千米)\/(?:秒|s|小时|h|hour)`),
		regexp.MustCompile(`\d+(?:\.\d+)?(?:米\/秒|m\/s|千米\/小时|km\/h|公里\/小时|英里\/小时|mph|节|knot)`),
		regexp.MustCompile(`\d+(?:\.\d+)?(?:次|个|件|台|部|辆|本|张|例|起|回|批|组)\/(?:分钟|秒|小时|天|月|年|周|星期)`),
		regexp.MustCompile(`每\s*(?:小时|分钟|秒钟?|天|月|年|周|星期|季度|学期|公里|米|千米)\s*\d+(?:\.\d+)?\s*(?:次|个|件|台|部|辆|本|张|例|起|回|批|组)`),
		regexp.MustCompile(`每\s*\d+(?:\.\d+)?\s*(?:小时|分钟|秒钟?|天|月|年|周|星期|季度|学期|公里|米|千米)\s*\d+(?:\.\d+)?\s*(?:次|个|件|台|部|辆|本|张|例|起|回|批|组)`),
		regexp.MustCompile(`\d{4}[-至到]\d{4}年`),
	}

	// Pre-compiled basic unit patterns
	basicPatterns = []*regexp.Regexp{
		// Date
		regexp.MustCompile(`\d{4}[-/\.年]\d{1,2}[-/\.月]\d{1,2}日?`),
		regexp.MustCompile(`\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4}`),
		regexp.MustCompile(`\d{1,2}月\d{1,2}[日号]`),
		// Add standalone year pattern
		regexp.MustCompile(`\d{4}年`),
		// Time
		regexp.MustCompile(`\d{1,2}[:：][0-5]\d([:：][0-5]\d)?`),
		regexp.MustCompile(`\d{1,2}时[0-5]?\d?分([0-5]?\d秒)?`),
		regexp.MustCompile(`\d+(?:\.\d+)?小时`),
		regexp.MustCompile(`\d+(?:\.\d+)?分钟`),
		regexp.MustCompile(`\d+(?:\.\d+)?秒钟?`),
		// Frame rate
		regexp.MustCompile(`\d+(?:\.\d+)?(?:fps|帧\/秒|frame\/s|Hz|赫兹)`),
		// Percentage
		regexp.MustCompile(`\d+(?:\.\d+)?(?:%|％|percent|百分点)`),
		regexp.MustCompile(`[增长降减]超?\d+(?:\.\d+)?(?:%|％|percent|百分比|百分点)`),
		regexp.MustCompile(`占比[从]?\d+(?:\.\d+)?(?:%|％)`),
		regexp.MustCompile(`占比[从]?\d+(?:\.\d+)?(?:%|％)[提升至到]\d+(?:\.\d+)?(?:%|％)`),
		// Weight
		regexp.MustCompile(`\d+(?:\.\d+)?(?:千克|公斤|kg|KG|斤|克|g|毫克|mg|吨|t)`),
		// Length
		regexp.MustCompile(`\d+(?:\.\d+)?(?:米|m|厘米|cm|毫米|mm|千米|km|公里|里|英寸|英尺|ft|foot|feet|英里|mile)`),
		// Area
		regexp.MustCompile(`\d+(?:\.\d+)?(?:平方米|平米|㎡|m²|m2|平方千米|平方公里|km²|km2|公顷|hectare|ha|亩)`),
		// Volume
		regexp.MustCompile(`\d+(?:\.\d+)?(?:立方米|m³|m3|立方厘米|cm³|cm3|升|l|L|毫升|ml|mL)`),
		// Temperature
		regexp.MustCompile(`\d+(?:\.\d+)?(?:℃|°C|摄氏度|℉|°F|华氏度|K|开尔文)`),
		// Storage
		regexp.MustCompile(`\d+(?:\.\d+)?(?:\s*[KkMmGgTtPp]?[Bb]|字节|比特|[Bb]yte|[Bb]it)`),
		// Energy
		regexp.MustCompile(`\d+(?:\.\d+)?(?:焦耳|J|kJ|卡路里|cal|kcal|千卡|瓦特|W|kW|MW|GW|千瓦时|kWh)`),
		// Pressure
		regexp.MustCompile(`\d+(?:\.\d+)?(?:帕|Pa|kPa|MPa|巴|bar|psi|毫米汞柱|mmHg)`),
		// Money
		regexp.MustCompile(`(?:￥|\$|€|£|¥)?\d+(?:\.\d+)?(?:元|块|万元|亿元|万亿元|美元|欧元|日元|英镑)?`),
		regexp.MustCompile(`\d+(?:\.\d+)?(?:元|块|万元|亿元|万亿元|万亿|千亿|百亿|十亿|美元|欧元|日元|英镑)`),
		regexp.MustCompile(`\d+(?:\.\d+)?万亿`),
		// Multiples
		regexp.MustCompile(`\d+(?:\.\d+)?倍`),
		// Quantity
		regexp.MustCompile(`\d+(?:\.\d+)?(?:个|只|台|部|辆|件|箱|瓶|盒|张|本|册|支|根|双|对|枚|套|组)`),
		// Years
		regexp.MustCompile(`(?:十|百|千|万)?[一二三四五六七八九十]年(?:间)?`),
	}
)

// hasUnit checks if a string contains a unit (not just a standalone number)
func hasUnit(text string) bool {
	// Remove all whitespace
	text = strings.TrimSpace(text)

	// Check if it's just a number (possibly with commas or decimal point)
	if matched, _ := regexp.MatchString(`^[\d,\.]+$`, text); matched {
		return false
	}

	// Check if it contains any non-digit character after the number
	numPattern := regexp.MustCompile(`^[\d,\.]+`)
	numStr := numPattern.FindString(text)

	// If the string is just the number without any trailing characters, it has no unit
	if numStr == text {
		return false
	}

	// Extract what comes after the number
	unitPart := strings.TrimPrefix(text, numStr)
	unitPart = strings.TrimSpace(unitPart)

	// If there's nothing after the number, it has no unit
	if unitPart == "" {
		return false
	}

	return true
}

// ExtractNumbersWithUnits extracts numbers with units from text and their position information
// including special formats like resolutions and ratios.
// Adjacent numbers with units will be merged into one entity.
func ExtractNumbersWithUnits(text string) []Match {
	// Store match results
	matches := []Match{}

	// Record matched positions
	matchedPositions := make(map[int]bool)

	// First phase: identify special formats and compound units
	for _, pattern := range specialFormatPatterns {
		for _, match := range pattern.FindAllStringIndex(text, -1) {
			start, end := match[0], match[1]

			// Check if overlaps with already matched regions
			overlaps := false
			for i := start; i < end; i++ {
				if matchedPositions[i] {
					overlaps = true
					break
				}
			}

			if !overlaps {
				originalText := text[start:end]

				// Skip if it's just a standalone number without units
				if !hasUnit(originalText) {
					continue
				}

				matches = append(matches, Match{
					OriginalText: originalText,
					StartPos:     start,
					EndPos:       end,
				})

				// Record matched positions
				for i := start; i < end; i++ {
					matchedPositions[i] = true
				}
			}
		}
	}

	// Second phase: identify basic unit patterns
	for _, pattern := range basicPatterns {
		for _, match := range pattern.FindAllStringIndex(text, -1) {
			start, end := match[0], match[1]

			// Check if overlaps with already matched regions
			overlaps := false
			for i := start; i < end; i++ {
				if matchedPositions[i] {
					overlaps = true
					break
				}
			}

			if !overlaps {
				originalText := text[start:end]

				// Skip if it's just a standalone number without units
				if !hasUnit(originalText) {
					continue
				}

				matches = append(matches, Match{
					OriginalText: originalText,
					StartPos:     start,
					EndPos:       end,
				})

				// Record matched positions
				for i := start; i < end; i++ {
					matchedPositions[i] = true
				}
			}
		}
	}

	// Sort results by position in text
	sort.Slice(matches, func(i, j int) bool {
		return matches[i].StartPos < matches[j].StartPos
	})

	// Merge adjacent matches with units
	mergedMatches := []Match{}
	i := 0
	for i < len(matches) {
		currentMatch := matches[i]
		mergedMatch := Match{
			OriginalText: currentMatch.OriginalText,
			StartPos:     currentMatch.StartPos,
			EndPos:       currentMatch.EndPos,
		}

		// Try to merge with subsequent adjacent matches
		nextIdx := i + 1
		for nextIdx < len(matches) {
			nextMatch := matches[nextIdx]

			// Check text between matches
			betweenText := text[mergedMatch.EndPos:nextMatch.StartPos]

			// If no text or only whitespace between matches, merge them
			if strings.TrimSpace(betweenText) == "" || len(betweenText) <= 2 {
				// Update merged match
				mergedMatch.OriginalText = text[mergedMatch.StartPos:nextMatch.EndPos]
				mergedMatch.EndPos = nextMatch.EndPos
				nextIdx++
			} else {
				// If cannot merge, exit loop
				break
			}
		}

		mergedMatches = append(mergedMatches, mergedMatch)
		i = nextIdx
	}

	return mergedMatches
}

// AreEquivalentNumbersWithUnits determines if two number+unit strings represent the same quantity
// It checks both that the numerical values are equal and that the units are equivalent
// For example: "1,000 meters" and "1000 米" would be considered equivalent
func AreEquivalentNumbersWithUnits(num1 string, num2 string) bool {
	// Extract number and unit from each string
	number1, unit1 := extractNumberAndUnit(num1)
	number2, unit2 := extractNumberAndUnit(num2)

	// Check if numbers are equal
	if number1 != number2 {
		return false
	}

	// Check if units are equivalent
	return areEquivalentUnits(unit1, unit2)
}

// extractNumberAndUnit separates a string into its numerical value and unit parts
// Returns the normalized number as a float64 and the unit as a string
func extractNumberAndUnit(input string) (float64, string) {
	// Remove all whitespace
	input = strings.Join(strings.Fields(input), "")

	// Extract the numeric part
	numPattern := regexp.MustCompile(`^[\d,\.]+`)
	numStr := numPattern.FindString(input)

	// Normalize the number string (remove commas and other formatting)
	numStr = strings.ReplaceAll(numStr, ",", "")

	// Convert the number string to float64
	num, err := strconv.ParseFloat(numStr, 64)
	if err != nil {
		// Return 0 if parsing fails
		num = 0
	}

	// Extract the unit part (everything after the number)
	unit := strings.TrimPrefix(input, numStr)
	unit = strings.TrimSpace(unit)

	return num, unit
}

// areEquivalentUnits determines if two unit strings represent the same unit of measurement
func areEquivalentUnits(unit1, unit2 string) bool {
	// If units are identical, they're equivalent
	if unit1 == unit2 {
		return true
	}

	// Map of equivalent units
	unitEquivalences := map[string][]string{
		// Length units
		"m":  {"米", "公尺", "meter", "meters"},
		"km": {"公里", "千米", "kilometer", "kilometers"},
		"cm": {"厘米", "公分", "centimeter", "centimeters"},
		"mm": {"毫米", "公厘", "millimeter", "millimeters"},

		// Weight units
		"kg": {"公斤", "千克", "kilogram", "kilograms"},
		"g":  {"克", "公克", "gram", "grams"},
		"mg": {"毫克", "公毫", "milligram", "milligrams"},
		"t":  {"吨", "公吨", "ton", "tons", "tonne", "tonnes"},

		// Volume units
		"l":  {"升", "公升", "立升", "liter", "liters", "litre", "litres", "L"},
		"ml": {"毫升", "公毫升", "milliliter", "milliliters", "millilitre", "millilitres", "mL"},

		// Currency units
		"元":  {"块", "人民币", "rmb", "yuan", "CNY", "￥"},
		"美元": {"dollar", "dollars", "$", "USD"},
		"欧元": {"euro", "euros", "€", "EUR"},
		"日元": {"yen", "JPY", "¥"},

		// Large numbers
		"万":  {"ten thousand", "10k"},
		"亿":  {"hundred million", "100M"},
		"万亿": {"trillion", "1T"},

		// Time units
		"s":   {"秒", "second", "seconds"},
		"min": {"分", "分钟", "minute", "minutes"},
		"h":   {"小时", "时", "hour", "hours"},
		"d":   {"天", "日", "day", "days"},

		// Percentage
		"%": {"％", "percent", "百分比", "百分点"},

		// Temperature
		"°C": {"℃", "摄氏度", "摄氏", "度", "centigrade"},
		"°F": {"℉", "华氏度", "华氏", "fahrenheit"},

		// Rate/speed units
		"m/s":  {"米/秒", "米每秒", "meter per second", "meters per second"},
		"km/h": {"公里/小时", "千米/小时", "公里每小时", "kilometer per hour", "kilometers per hour"},
	}

	// Normalize units by removing spaces and converting to lowercase
	normalizedUnit1 := strings.ToLower(strings.Join(strings.Fields(unit1), ""))
	normalizedUnit2 := strings.ToLower(strings.Join(strings.Fields(unit2), ""))

	// Check unit1 against all equivalent units
	for baseUnit, equivalents := range unitEquivalences {
		// Check if unit1 matches the base unit or any equivalent
		isUnit1Match := normalizedUnit1 == strings.ToLower(baseUnit)
		if !isUnit1Match {
			for _, equiv := range equivalents {
				if normalizedUnit1 == strings.ToLower(strings.Join(strings.Fields(equiv), "")) {
					isUnit1Match = true
					break
				}
			}
		}

		// If unit1 matches, check unit2 against the same group
		if isUnit1Match {
			if normalizedUnit2 == strings.ToLower(baseUnit) {
				return true
			}
			for _, equiv := range equivalents {
				if normalizedUnit2 == strings.ToLower(strings.Join(strings.Fields(equiv), "")) {
					return true
				}
			}
		}
	}

	// Handle compound units like "万亿元" vs "万亿"
	// For basic comparison, we check if one unit is contained within the other
	if strings.Contains(normalizedUnit1, normalizedUnit2) ||
		strings.Contains(normalizedUnit2, normalizedUnit1) {
		return true
	}

	// Units are not equivalent
	return false
}

// AreEquivalentMatches determines if two Match objects represent the same quantity
// by comparing their numerical values and units for equivalence
func AreEquivalentMatches(match1, match2 Match) bool {
	return AreEquivalentNumbersWithUnits(match1.OriginalText, match2.OriginalText)
}

// GetNormalizedNumericValue extracts and normalizes the numeric value from a Match
// Returns the normalized number as a float64 and success flag
func GetNormalizedNumericValue(match Match) (float64, bool) {
	number, _ := extractNumberAndUnit(match.OriginalText)
	return number, true
}

// GetNormalizedUnit extracts and normalizes the unit from a Match
// Returns the unit string and success flag
func GetNormalizedUnit(match Match) (string, bool) {
	_, unit := extractNumberAndUnit(match.OriginalText)
	return unit, true
}

var tagBlockRe = regexp.MustCompile(`(?s)<(?:cite|highlight)[^>]*?>.*?</(?:cite|highlight)>`)

func ReplaceOutsideProtectedTags(source, keyword, replacement string) string {
	// 切分所有非 tag 内的部分
	parts := tagBlockRe.Split(source, -1)
	matches := tagBlockRe.FindAllString(source, -1)

	var result strings.Builder
	for i, part := range parts {
		part = strings.ReplaceAll(part, keyword, replacement)
		result.WriteString(part)
		if i < len(matches) {
			result.WriteString(matches[i])
		}
	}
	return result.String()
}
