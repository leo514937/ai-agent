import re
import ast
from pathlib import Path

# 1. Add mixin properties to all adapter files
adapters_dir = Path("src/learning_agent_service/application/workflow/adapters")
for f in adapters_dir.glob("stages_*.py"):
    content = f.read_text(encoding="utf-8")
    
    # Add dummy attributes to Mixin classes to satisfy Pyright
    mixin_props = """
        container: "Any"
        _plan_executor: "Any"
        plan_planner: "Any"
        plan_validator: "Any"
        step_executor: "Any"
        progress_checker: "Any"
        plan_reviewer: "Any"
        replanner: "Any"
        human_approval_stub: "Any"
        business_client: "Any"
"""
    new_content = re.sub(r"(class WorkflowNodeAdapter[a-zA-Z0-9_]+Mixin:)\s*(def |$)", r"\1" + mixin_props + r"        \2", content)
    
    if new_content != content:
        f.write_text(new_content, encoding="utf-8")

# 2. Fix stages_front_a.py missing import
front_a = adapters_dir / "stages_front_a.py"
if front_a.exists():
    c = front_a.read_text(encoding="utf-8")
    if "from learning_agent_service.local_life.entity_resolver import normalize_local_life_query" not in c:
        c = c.replace("from learning_agent_service.application.rag_gate import RagGateRequest", "from learning_agent_service.local_life.entity_resolver import normalize_local_life_query\nfrom learning_agent_service.application.rag_gate import RagGateRequest")
        front_a.write_text(c, encoding="utf-8")

# 3. Replace `from .helpers import *` with explicit imports
def expand_star_imports(file_path):
    c = file_path.read_text(encoding="utf-8")
    if "from .helpers import *" not in c:
        return
    
    # Find all undefined names in the file using ast
    tree = ast.parse(c)
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names.add(node.id)
    
    # Read helpers to find what they export
    helpers_c = (adapters_dir / "helpers.py").read_text(encoding="utf-8")
    helpers_tree = ast.parse(helpers_c)
    exported = set()
    for node in helpers_tree.body:
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.ClassDef):
            exported.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    exported.add(t.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                exported.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                exported.add(alias.asname or alias.name)
    
    # Intersection
    to_import = sorted(used_names.intersection(exported))
    import_stmt = "from .helpers import (\n    " + ",\n    ".join(to_import) + ",\n)"
    c = c.replace("from .helpers import *", import_stmt)
    file_path.write_text(c, encoding="utf-8")

expand_star_imports(adapters_dir / "stages_back_core.py")
expand_star_imports(adapters_dir / "stages_back.py")
