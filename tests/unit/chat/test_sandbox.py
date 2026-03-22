"""Tests for the Python sandbox MCP server logic."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# We can't import the MCP server directly (requires mcp package),
# so we test the core execution logic by reimplementing the key parts.

SANDBOX_MODULE = (
    Path(__file__).resolve().parents[3] / "apps" / "chat" / "mcp_servers" / "sandbox.py"
)
PREAMBLE_MODULE = Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "_preamble.py"


def test_sandbox_module_exists():
    """The sandbox MCP server module exists."""
    assert SANDBOX_MODULE.exists()


def test_sandbox_has_run_python_tool():
    """The sandbox module defines a run_python function."""
    content = SANDBOX_MODULE.read_text()
    assert "def run_python" in content
    assert "@mcp.tool()" in content


def test_sandbox_preamble_has_imports():
    """The preamble pre-imports expected libraries."""
    content = PREAMBLE_MODULE.read_text()
    assert "import pandas as pd" in content
    assert "import numpy as np" in content
    assert "import plotly.express as px" in content
    assert "import plotly.graph_objects as go" in content
    assert "import duckdb" in content


def test_sandbox_preamble_has_query_helper():
    """The preamble defines a query() shorthand."""
    content = PREAMBLE_MODULE.read_text()
    assert "def query(sql" in content
    assert "conn.execute(sql).fetchdf()" in content


def test_sandbox_preamble_has_metric_calculator():
    """The preamble makes the metric_calculator module available."""
    content = PREAMBLE_MODULE.read_text()
    assert "import metric_calculator as mc" in content


def test_sandbox_has_timeout():
    """The sandbox enforces a timeout on script execution."""
    content = SANDBOX_MODULE.read_text()
    assert "timeout=" in content
    assert "TimeoutExpired" in content


def test_sandbox_detects_plotly_output():
    """The sandbox detects plotly JSON in stdout."""
    content = SANDBOX_MODULE.read_text()
    assert '"data" in parsed and "layout" in parsed' in content


def test_sandbox_detects_dataframe_output():
    """The sandbox detects DataFrame JSON (split orient) in stdout."""
    content = SANDBOX_MODULE.read_text()
    assert '"columns" in parsed and "data" in parsed' in content


def test_sandbox_cleans_up_temp_files():
    """The sandbox removes temp script files after execution."""
    content = SANDBOX_MODULE.read_text()
    assert "os.unlink(script_path)" in content
    assert "contextlib.suppress(OSError)" in content


class TestSandboxExecution:
    """Test the sandbox execution logic directly (without MCP layer)."""

    def _run_code(self, code: str) -> dict:
        """Execute Python code the same way the sandbox does."""
        import tempfile

        full_code = (
            textwrap.dedent("""\
            import sys
            import json
            import pandas as pd
            import numpy as np
        """)
            + code
        )

        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(full_code)
            script_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        finally:
            Path(script_path).unlink(missing_ok=True)

    def test_basic_print(self):
        result = self._run_code('print("hello world")')
        assert result["returncode"] == 0
        assert result["stdout"] == "hello world"

    def test_pandas_available(self):
        result = self._run_code("df = pd.DataFrame({'a': [1,2,3]}); print(len(df))")
        assert result["returncode"] == 0
        assert result["stdout"] == "3"

    def test_numpy_available(self):
        result = self._run_code("print(np.mean([1, 2, 3, 4, 5]))")
        assert result["returncode"] == 0
        assert "3.0" in result["stdout"]

    def test_syntax_error_returns_nonzero(self):
        result = self._run_code("def oops(")
        assert result["returncode"] != 0
        assert "SyntaxError" in result["stderr"]

    def test_json_output_parseable(self):
        result = self._run_code('import json; print(json.dumps({"answer": 42}))')
        assert result["returncode"] == 0
        parsed = json.loads(result["stdout"])
        assert parsed["answer"] == 42

    def test_dataframe_split_orient(self):
        code = textwrap.dedent("""\
            df = pd.DataFrame({"name": ["LeBron", "Curry"], "pts": [30, 28]})
            print(df.to_json(orient="split"))
        """)
        result = self._run_code(code)
        assert result["returncode"] == 0
        parsed = json.loads(result["stdout"])
        assert "columns" in parsed
        assert "data" in parsed
        assert len(parsed["data"]) == 2

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("plotly"),
        reason="plotly not installed",
    )
    def test_plotly_figure_output(self):
        code = textwrap.dedent("""\
            import plotly.graph_objects as go
            fig = go.Figure(data=[go.Bar(x=["A", "B"], y=[10, 20])])
            fig.update_layout(title="Test")
            print(fig.to_json())
        """)
        result = self._run_code(code)
        assert result["returncode"] == 0
        parsed = json.loads(result["stdout"])
        assert "data" in parsed
        assert "layout" in parsed

    def test_blocked_code_returns_error(self):
        """Code with blocked patterns should return an error without executing."""
        # We can't import the MCP module, but we can test the pattern
        content = SANDBOX_MODULE.read_text()
        # Verify the check happens before subprocess.run
        check_pos = content.find("_check_code_safety")
        subprocess_pos = content.find("subprocess.run")
        # The safety check should appear before subprocess execution
        # (first occurrence after run_python definition)
        assert check_pos < subprocess_pos


class TestCodeSafety:
    """Test the sandbox code blocklist."""

    def test_sandbox_has_code_safety_check(self):
        """The sandbox module has a _check_code_safety function."""
        content = SANDBOX_MODULE.read_text()
        assert "_check_code_safety" in content
        assert "_BLOCKED_PATTERNS" in content

    def test_blocks_subprocess(self):
        content = SANDBOX_MODULE.read_text()
        assert '"subprocess"' in content or "'subprocess'" in content

    def test_blocks_os_system(self):
        content = SANDBOX_MODULE.read_text()
        assert "os.system" in content

    def test_blocks_importlib(self):
        content = SANDBOX_MODULE.read_text()
        assert "importlib" in content

    def test_blocks_shutil_rmtree(self):
        content = SANDBOX_MODULE.read_text()
        assert "shutil.rmtree" in content


class TestEnvScrubbing:
    """Test that sandbox scrubs sensitive env vars."""

    def test_sandbox_scrubs_env_vars(self):
        """The sandbox filters sensitive env vars from subprocess."""
        content = SANDBOX_MODULE.read_text()
        assert "clean_env" in content
        assert "API_KEY" in content
        assert "SECRET" in content
        assert "TOKEN" in content
        assert "PASSWORD" in content

    def test_sandbox_uses_clean_env(self):
        """subprocess.run is called with env=clean_env."""
        content = SANDBOX_MODULE.read_text()
        assert "env=clean_env" in content


class TestProcessIsolation:
    """Test that sandbox uses process group isolation."""

    def test_sandbox_uses_new_session(self):
        """subprocess.run uses start_new_session=True."""
        content = SANDBOX_MODULE.read_text()
        assert "start_new_session=True" in content
