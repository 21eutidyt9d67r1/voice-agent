"""Offline contracts for the Linux/WSL local setup entry points."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts" / "setup-local-examples.sh"
LOGIN = ROOT / "scripts" / "login-devtunnel.sh"
MCP_E2E = ROOT / "shared_mcp" / "scripts" / "e2e-local.sh"


def shell_function(source: str, name: str) -> str:
    start = source.index(f"{name}() {{")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


class LocalSetupScriptContractTests(unittest.TestCase):
    def test_shell_entry_points_parse(self):
        subprocess.run(
            ["bash", "-n", str(SETUP), str(LOGIN)],
            check=True,
            cwd=ROOT,
        )

    def test_minimal_python_can_bootstrap_component_pip(self):
        source = SETUP.read_text(encoding="utf-8")
        installer = shell_function(source, "install_python_environment")

        self.assertIn("import ensurepip", installer)
        self.assertIn("venv --without-pip", installer)
        self.assertIn("https://bootstrap.pypa.io/get-pip.py", installer)
        self.assertIn('"${python}" -m pip --version', installer)

    def test_setup_covers_both_independent_finance_runtimes(self):
        source = SETUP.read_text(encoding="utf-8")
        for variable, folder in (
            ("HANDOFF_ROOT", "example1_finance_with_handoff_realtime"),
            ("CASCADE_ROOT", "example1_finance_with_handoff_cascade"),
        ):
            with self.subTest(folder=folder):
                self.assertIn(f'{variable}="${{SAMPLES_ROOT}}/{folder}"', source)
                self.assertIn(f'install_python_environment "${{{variable}}}"', source)
                self.assertIn(f'"${{{variable}}}/.venv/bin/python"', source)
                self.assertIn(f'check_env_file "${{{variable}}}/.env"', source)
                self.assertTrue((ROOT / "samples" / folder / "sample.py").is_file())
        self.assertIn(
            'HANDOFF_SAMPLE="${SAMPLES_ROOT}/example1_finance_with_handoff_realtime"',
            MCP_E2E.read_text(encoding="utf-8"),
        )

    def test_devtunnel_login_uses_repo_cli_and_mcp_working_directory(self):
        source = LOGIN.read_text(encoding="utf-8")

        self.assertIn(".local-tools/devtunnel/bin/devtunnel", source)
        self.assertIn("user login --github --use-device-code-auth", source)
        self.assertNotIn("--entra", source)
        self.assertIn('cd "${ROOT}/shared_mcp"', source)
        self.assertIn("--use-device-code-auth", source)

    def test_setup_recommends_github_devtunnel_login(self):
        source = SETUP.read_text(encoding="utf-8")
        authentication = shell_function(source, "check_authentication")

        self.assertIn("required GitHub device-code authentication", authentication)
        self.assertIn("./scripts/login-devtunnel.sh", authentication)
        self.assertNotIn("For Microsoft Entra", authentication)

    def test_local_mcp_e2e_recommends_github_wrapper(self):
        source = MCP_E2E.read_text(encoding="utf-8")

        self.assertIn("scripts/login-devtunnel.sh", source)
        self.assertNotIn("--entra", source)


if __name__ == "__main__":
    unittest.main()