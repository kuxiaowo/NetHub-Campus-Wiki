"""Regression checks for the Linux deployment initializer."""

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = PROJECT_ROOT / "scripts" / "init_linux.sh"
FRONTEND_INIT_SCRIPT = PROJECT_ROOT / "scripts" / "init_frontend_linux.sh"
BACKEND_INIT_SCRIPT = PROJECT_ROOT / "scripts" / "init_backend_linux.sh"
COMMON_INIT_SCRIPT = PROJECT_ROOT / "scripts" / "init_linux_common.sh"
FRONTEND_REQUIREMENTS = PROJECT_ROOT / "requirements-frontend.txt"


class LinuxInitScriptTest(unittest.TestCase):
    def test_entry_points_select_the_expected_deployment_mode(self) -> None:
        self.assertIn(
            'run_initializer "all" "$@"',
            INIT_SCRIPT.read_text(encoding="utf-8"),
        )
        self.assertIn(
            'run_initializer "frontend" "$@"',
            FRONTEND_INIT_SCRIPT.read_text(encoding="utf-8"),
        )
        self.assertIn(
            'run_initializer "backend" "$@"',
            BACKEND_INIT_SCRIPT.read_text(encoding="utf-8"),
        )

    def test_frontend_has_a_minimal_dependency_set(self) -> None:
        dependencies = [
            line.strip()
            for line in FRONTEND_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        self.assertEqual(dependencies, ["python-dotenv==1.0.1"])

    def test_component_actions_are_mode_guarded(self) -> None:
        script = COMMON_INIT_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('if [[ "$mode" != "frontend" ]]; then\n    prepare_backend', script)
        self.assertIn('if [[ "$mode" != "frontend" ]]; then\n    write_api_unit', script)
        self.assertIn('if [[ "$mode" != "backend" ]]; then\n    write_frontend_unit', script)
        self.assertIn('if [[ "$mode" == "frontend" ]]; then', script)
        self.assertIn('--requirement "$FRONTEND_REQUIREMENTS"', script)

    def test_frontend_only_unit_has_no_local_api_dependency(self) -> None:
        script = COMMON_INIT_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('local unit_dependencies="After=network.target"', script)
        self.assertIn('if [[ "$mode" == "all" ]]; then', script)
        self.assertIn('Wants=$API_UNIT', script)

    def test_backend_and_combined_modes_keep_admin_arguments(self) -> None:
        script = COMMON_INIT_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            '[[ "$mode" != "frontend" ]] || die "前端初始化不支持 --admin"',
            script,
        )
        self.assertIn(
            'python -m backend.bootstrap_admin "${admin_args[@]}"',
            script,
        )

    def test_systemd_path_directives_do_not_quote_absolute_paths(self) -> None:
        script = COMMON_INIT_SCRIPT.read_text(encoding="utf-8")

        self.assertEqual(script.count("WorkingDirectory=$PROJECT_DIR"), 2)
        self.assertEqual(script.count("EnvironmentFile=$ENV_FILE"), 2)
        self.assertNotIn('WorkingDirectory="$PROJECT_DIR"', script)
        self.assertNotIn('EnvironmentFile="$ENV_FILE"', script)


if __name__ == "__main__":
    unittest.main()
