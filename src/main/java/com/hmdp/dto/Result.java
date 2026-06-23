package com.hmdp.dto;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
public class Result {
    private Boolean success;
    private String errorMsg;
    private Object data;
    private Long total;

    // Compatibility fields for the Next.js frontend
    private Integer code;
    private String message;

    public Result(Boolean success, String errorMsg, Object data, Long total) {
        this.success = success;
        this.errorMsg = errorMsg;
        this.data = data;
        this.total = total;
        this.code = success ? 200 : 500;
        this.message = success ? "success" : errorMsg;
    }

    public Result(Boolean success, String errorMsg, Object data, Long total, Integer code, String message) {
        this.success = success;
        this.errorMsg = errorMsg;
        this.data = data;
        this.total = total;
        this.code = code;
        this.message = message;
    }

    public static Result ok(){
        return new Result(true, null, null, null);
    }
    public static Result ok(Object data){
        return new Result(true, null, data, null);
    }
    public static Result ok(List<?> data, Long total){
        return new Result(true, null, data, total);
    }
    public static Result fail(String errorMsg){
        return new Result(false, errorMsg, null, null);
    }
}
