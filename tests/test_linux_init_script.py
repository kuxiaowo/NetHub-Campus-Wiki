"""Regression checks for the Linux deployment initializer."""

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = PROJECT_ROOT / "scripts" / "init_linux.sh"


class LinuxInitScriptTest(unittest.TestCase):
    def test_systemd_path_directives_do_not_quote_absolute_paths(self) -> None:
        script = INIT_SCRIPT.read_text(encoding="utf-8")

        self.assertEqual(script.count("WorkingDirectory=$PROJECT_DIR"), 2)
        self.assertEqual(script.count("EnvironmentFile=$ENV_FILE"), 2)
        self.assertNotIn('WorkingDirectory="$PROJECT_DIR"', script)
        self.assertNotIn('EnvironmentFile="$ENV_FILE"', script)


if __name__ == "__main__":
    unittest.main()
