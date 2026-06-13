import re
from pathlib import Path

adapters_dir = Path("src/learning_agent_service/application/workflow/adapters")

# Remove previous wrong injection
for f in adapters_dir.glob("stages_*.py"):
    content = f.read_text(encoding="utf-8")
    lines = content.split("\n")
    new_lines = []
    for line in lines:
        if line.strip() in [
            "container: 'Any'",
            "_plan_executor: 'Any'",
            "plan_planner: 'Any'",
            "plan_validator: 'Any'",
            "step_executor: 'Any'",
            "progress_checker: 'Any'",
            "plan_reviewer: 'Any'",
            "replanner: 'Any'",
            "human_approval_stub: 'Any'",
            "business_client: 'Any'",
        ]:
            continue
        new_lines.append(line)
    
    # Now inject with correct indentation
    final_lines = []
    i = 0
    while i < len(new_lines):
        line = new_lines[i]
        final_lines.append(line)
        if line.startswith("class WorkflowNodeAdapter") and "Mixin" in line and ":" in line:
            # find next non-empty line's indentation
            indent = "    "
            for j in range(i + 1, len(new_lines)):
                next_line = new_lines[j]
                if next_line.strip():
                    # get leading spaces
                    spaces = len(next_line) - len(next_line.lstrip())
                    indent = " " * spaces
                    break
            
            final_lines.append(indent + "container: 'Any'")
            final_lines.append(indent + "_plan_executor: 'Any'")
            final_lines.append(indent + "plan_planner: 'Any'")
            final_lines.append(indent + "plan_validator: 'Any'")
            final_lines.append(indent + "step_executor: 'Any'")
            final_lines.append(indent + "progress_checker: 'Any'")
            final_lines.append(indent + "plan_reviewer: 'Any'")
            final_lines.append(indent + "replanner: 'Any'")
            final_lines.append(indent + "human_approval_stub: 'Any'")
            final_lines.append(indent + "business_client: 'Any'")
        i += 1

    new_content = "\n".join(final_lines)
    if new_content != content:
        f.write_text(new_content, encoding="utf-8")
