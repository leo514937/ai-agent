"""Fix relative imports in subgraph modules.

Files in engine/subgraphs/ use `..` for sibling engine modules correctly
(e.g. .._compat, .._routes), but need `...` for modules at the
local_life_agent package level (e.g. ...domain, ...llm, ...input).
"""

import re
import os

SUBDIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_MODULES = {"_compat", "_routes", "nodes", "session_write"}

def fix_file(path: str) -> bool:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Pattern: from ..<module> (not in ENGINE_MODULES) import ...
    # Or: from ..<module>.<submodule> import ...
    def replace_import(match):
        prefix = match.group(1)  # "from .."
        module = match.group(2)  # e.g., "domain", "llm", "domain.enums"
        rest = match.group(3)   # e.g., " import ..."
        # Extract the top-level module name
        top_module = module.split(".")[0]
        if top_module not in ENGINE_MODULES:
            return f"from ...{module}{rest}"
        return match.group(0)

    pattern = r'(from \.\.)([a-zA-Z_][\w.]*)(\s+import\s+)'
    new_content = re.sub(pattern, replace_import, content)

    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False

def main():
    fixed = []
    for fname in os.listdir(SUBDIR):
        if fname.endswith(".py") and fname != "_fix_imports.py" and fname != "__init__.py":
            path = os.path.join(SUBDIR, fname)
            if fix_file(path):
                fixed.append(fname)
    if fixed:
        print(f"Fixed: {', '.join(fixed)}")
    else:
        print("No changes needed.")

if __name__ == "__main__":
    main()
