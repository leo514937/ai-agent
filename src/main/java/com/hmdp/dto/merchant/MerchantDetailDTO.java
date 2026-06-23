package com.hmdp.dto.merchant;

import lombok.Data;
import lombok.EqualsAndHashCode;
import java.util.List;

@Data
@EqualsAndHashCode(callSuper = true)
public class MerchantDetailDTO extends MerchantDTO {
    private List<MerchantServiceDTO> services;
    private List<MerchantCommentDTO> comments;
}
