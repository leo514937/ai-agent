# -*- coding: utf-8 -*-
import os

def main():
    path = r"d:\javacode\hm-dianping\doc\progress.md"
    if not os.path.exists(path):
        print("progress.md does not exist!")
        return

    with open(path, "rb") as f:
        content = f.read()

    # Search for target signature
    target_str = "  - **结果**：全套 87 个高覆盖率单元/集成测试 100% 绿灯，系统逻辑毫无破损，用户体验完备无瑕。"
    target_bytes = target_str.encode("utf-8")
    
    idx = content.find(target_bytes)
    if idx == -1:
        # Try with slightly shorter clean end
        target_str = "  - 本地生活 P0 核心测试集（20个测试用例）：`test_p0_context_contract.py` 与 `test_p0_routing_review.py` 全部 100% 通过。"
        target_bytes = target_str.encode("utf-8")
        idx = content.find(target_bytes)
        
    if idx != -1:
        clean_len = idx + len(target_bytes)
        truncated = content[:clean_len]
        
        append_text = """

### 4. 深度诊断 Context Engineering 与 Harness Engineering 并生成正式评估报告
- **诊断任务完成**：对全项目进行了无死角的架构走访与源码静态审查，精准识别出上下文管理及测试框架工程的 9 大深水区隐患，涵盖多轮对话状态漂移与单元测试沙箱穿透。
- **产出评估报告**：编写并上线了本地 Markdown 评估文档 [context_and_harness_assessment.md](file:///d:/javacode/hm-dianping/doc/context_and_harness_assessment.md)，包含精美 Mermaid 时序与拓扑关系图：
  - **Context Engineering 4 大隐患**：详细论述了 `pending_user_need` 缺失意图漂移清理机制造成的上下文交叉污染漏洞、`recent_entities` 缺乏 LRU/衰减上限带来的 Redis 存储及 LLM 窗口过载隐患、列表型槽位 (`avoid`/`preferences`) 盲目合并产生的语义自我冲突故障，以及页面强绑定上下文阻碍意图主动跳转的局限性。
  - **Harness Engineering 5 大缺陷**：指出当前测试套件中 unit tests 越界访问物理 Redis/Qdrant 导致的沙箱击穿与 Flaky 问题、`ReplayHarness` 对流式 SSE 协议 delta 时序回放断言支持的空白、物理临时测试数据写入对公共资源的污染、硬编码 sleep 在 CI 环境中引起的脆弱超时，以及缺乏模拟高并发会话竞态的压测 Harness。
  - **制定长期路线图**：为下一阶段的框架级防线升级与全自动 SSE 仿真脚手架迭代提供了清晰、极具实操性的架构路线。
"""
        final_content = truncated + append_text.encode("utf-8")
        with open(path, "wb") as f:
            f.write(final_content)
        print("REPAIR_SUCCESS")
    else:
        print("TARGET_NOT_FOUND")

if __name__ == "__main__":
    main()
