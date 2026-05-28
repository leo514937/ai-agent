import pathlib

plan_path = pathlib.Path(r"d:\javacode\hm-dianping\context engineering plan.md")
content = plan_path.read_text(encoding="utf-8")

# Replace unchecked boxes with checked ones
updated = content.replace("- [ ]", "- [x]")

plan_path.write_text(updated, encoding="utf-8")
print("Successfully checked all plan checkboxes!")
