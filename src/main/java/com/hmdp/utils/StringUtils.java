package com.hmdp.utils;

import cn.hutool.core.util.StrUtil;

public class StringUtils {

    public static String firstNonBlank(String... values) {
        if (values == null) {
            return null;
        }
        for (String value : values) {
            if (StrUtil.isNotBlank(value)) {
                return value;
            }
        }
        return null;
    }

    public static String normalize(String text) {
        if (text == null) {
            return null;
        }
        return text.trim().toLowerCase();
    }

    public static String asString(Object value) {
        if (value == null) {
            return null;
        }
        return String.valueOf(value);
    }

    public static String defaultNumber(Integer value) {
        return value == null ? "0" : String.valueOf(value);
    }

    public static String formatScore(Integer score) {
        if (score == null) {
            return "0.0";
        }
        return String.format("%.1f", score / 10.0);
    }

    public static String formatPrice(Integer price) {
        if (price == null) {
            return "0";
        }
        return String.valueOf(price);
    }
}