package com.hmdp.ai.query.dto;

import com.hmdp.entity.User;
import com.hmdp.entity.UserInfo;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 用户上下文与关注关系的只读视图。
 */
@Data
@NoArgsConstructor
public class AiUserContextDigest {

    private User user;
    private UserInfo userInfo;
    private User targetUser;
    private UserInfo targetUserInfo;
    private Long targetUserId;
    private boolean followingTarget;
    private boolean targetFollowingCurrent;
    private List<String> highlights = new ArrayList<>();
}
