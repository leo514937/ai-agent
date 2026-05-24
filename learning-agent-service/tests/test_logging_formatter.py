import logging
import sys
import unittest

sys.path.insert(0, r"D:\javacode\hm-dianping\learning-agent-service\src")

from learning_agent_service.config.logging import PlainTextFormatter, StructuredJsonFormatter


class LoggingFormatterTest(unittest.TestCase):
    def test_structured_json_formatter_keeps_chinese(self) -> None:
        record = logging.LogRecord(
            name="demo",
            level=logging.INFO,
            pathname="x.py",
            lineno=1,
            msg="中文测试",
            args=(),
            exc_info=None,
        )

        output = StructuredJsonFormatter().format(record)

        self.assertIn("中文测试", output)
        self.assertNotIn("\\u4e2d\\u6587\\u6d4b\\u8bd5", output)

    def test_plain_text_formatter_keeps_chinese_context(self) -> None:
        record = logging.LogRecord(
            name="demo",
            level=logging.INFO,
            pathname="x.py",
            lineno=1,
            msg="中文测试",
            args=(),
            exc_info=None,
        )

        output = PlainTextFormatter().format(record)

        self.assertIn("中文测试", output)


if __name__ == "__main__":
    unittest.main()
