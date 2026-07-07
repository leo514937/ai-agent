# AI Chat 请求鉴权链路 — 架构记录

> 创建日期: 2026-07-05
> 范围: `src/main/java/com/hmdp/` 后端服务
> 主题: 用户从 `/ai/chat` 接口输入后的第一跳模块与鉴权实现细节

---

## 一、问题回顾

用户从 AI 服务的 `/ai/chat` 接口输入之后，数据第一步流向哪个模块？是否先经过网关鉴权？

## 二、结论

**不是网关鉴权。** 项目没有独立的网关服务。第一步是 Spring 拦截器链中的 **`RefreshTokenInterceptor`**（order=0），它拦截所有路径 `/**`，负责 token 刷新与用户身份获取。

## 三、完整链路（按执行顺序）

```
HTTP POST /ai/chat
  │
  ├─ [0] CORS Handler（MvcConfig.addCorsMappings）
  │    跨域处理，预检 OPTIONS 请求
  │
  ├─ [1] RefreshTokenInterceptor（order=0）
  │    ├─ 获取 authorization 请求头
  │    ├─ 无 token → 塞默认 mock 用户到 ThreadLocal
  │    ├─ 有 token → 查 Redis 获取用户信息 → 刷新 TTL
  │    └─ 总是返回 true（永不拦截）
  │
  ├─ [2] LoginInterceptor（order=1）— ⚠️ 已禁用
  │    被 MvcConfig 整段注释掉，当前不生效
  │
  └─ [3] AiAssistantController.chat()
       ├─ 参数校验（message 非空）
       ├─ 从 UserHolder.getUser() 取当前用户
       └─ 调用 AiAssistantService.chat()
```

## 四、关键代码位置

| 组件 | 文件 | 行号 |
|---|---|---|
| CORS 配置 | `src/main/java/com/hmdp/config/MvcConfig.java` | 35-43 |
| 拦截器注册 | `src/main/java/com/hmdp/config/MvcConfig.java` | 16-33 |
| RefreshTokenInterceptor | `src/main/java/com/hmdp/utils/RefreshTokenInterceptor.java` | 全文件 |
| LoginInterceptor（已注释） | `src/main/java/com/hmdp/utils/LoginInterceptor.java` | 全文件 |
| UserHolder（ThreadLocal） | `src/main/java/com/hmdp/utils/UserHolder.java` | 全文件 |
| AiAssistantController | `src/main/java/com/hmdp/controller/AiAssistantController.java` | 36-46 |

## 五、RefreshTokenInterceptor 鉴权细节

### 5.1 无 token 流程（匿名用户）

```java
// RefreshTokenInterceptor.java:26-33
String token = request.getHeader("authorization");
if (StrUtil.isBlank(token)) {
    // 默认塞一个测试用户，防止 AI Agent 调用后端报错 NPE
    UserDTO mockUser = new UserDTO();
    mockUser.setId(1010L);
    mockUser.setNickName("AI_Mock_User");
    UserHolder.saveUser(mockUser);
    return true;  // 永远放行
}
```

- 请求头不带 `authorization` → 创建 mock 用户（id=1010, nickName="AI_Mock_User"）
- **永不拦截**，总是 `return true`
- 设计意图：AI 页面允许未登录访问，但后端服务需要 UserDTO 对象，所以给了一个兜底 mock 用户

### 5.2 有 token 流程（已登录用户）

```java
// RefreshTokenInterceptor.java:35-48
Map<Object, Object> userMap = stringRedisTemplate.opsForHash()
        .entries(RedisConstants.LOGIN_USER_KEY + token);
if (userMap.isEmpty()) {
    return true;  // token 无效/过期，仍放行（没有 mock 用户）
}
UserDTO userDTO = BeanUtil.fillBeanWithMap(userMap, new UserDTO(), false);
UserHolder.saveUser(userDTO);
stringRedisTemplate.expire(RedisConstants.LOGIN_USER_KEY + token, ...);
```

- 从 Redis Hash 中查询 `LOGIN_USER_KEY + token`
- 查到 → 将用户信息存入 `UserHolder`（ThreadLocal），刷新 token TTL
- 查不到（token 过期/非法）→ **放行但也不塞 mock 用户**，此时 `UserHolder.getUser()` 返回 null

### 5.3 afterCompletion 清理

```java
// RefreshTokenInterceptor.java:51-54
@Override
public void afterCompletion(...) {
    UserHolder.removeUser();  // 请求结束，清除 ThreadLocal 防止内存泄漏
}
```

## 六、LoginInterceptor（已禁用）原本的逻辑

```java
// LoginInterceptor.java 整段被 MvcConfig 注释掉
if (UserHolder.getUser() == null) {
    response.setStatus(401);
    return false;  // 不再放行
}
```

- 检查 ThreadLocal 中是否有用户
- 无用户 → 返回 401，拦截
- `/ai/**` 路径原在 excludePathPatterns 中（AI 相关接口免登录）

**当前状态**：整段注册代码被注释，`LoginInterceptor.java` 文件保留但未使用。

## 七、架构要点总结

| 项目 | 当前状态 |
|---|---|
| 独立网关服务 | ❌ 无 |
| CORS 跨域配置 | ✅ 允许 localhost:3000 |
| Token 刷新拦截器 | ✅ 启用，order=0，全路径 |
| 登录状态拦截器 | ❌ 已禁用（整段注释） |
| 匿名用户兜底 | ✅ 无 token 时塞 mock 用户 (id=1010) |
| ThreadLocal 生命周期 | preHandle 设置，afterCompletion 清理 |
| 用户信息传递 | UserHolder (ThreadLocal) → 被 Service 层通过 `UserHolder.getUser()` 读取 |

## 八、注意事项

1. `RefreshTokenInterceptor` **并非严格的鉴网关**，它不拦截任何请求，也没有权限校验——它更像一个"用户身份解析 + Token 刷新"中间件。
2. 无 token 时塞 mock 用户（id=1010）的设计意味着**所有匿名 AI 请求共享同一个用户身份**，这在多用户场景下需要关注数据隔离。
3. `UserHolder.getUser()` 在无 token 且 token 过期时可能返回 `null`——`AiAssistantController` 和 `AiAssistantService` 需要处理这种情况。
