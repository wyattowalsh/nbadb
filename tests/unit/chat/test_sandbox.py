"""Tests for the Python sandbox MCP server logic."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_HAS_PLOTLY = __import__("importlib").util.find_spec("plotly") is not None

# We can't import the MCP server directly (requires mcp package),
# so we test the core execution logic by reimplementing the key parts.

SANDBOX_MODULE = (
    Path(__file__).resolve().parents[3] / "apps" / "chat" / "mcp_servers" / "sandbox.py"
)
SANDBOX_EXEC_MODULE = (
    Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "_sandbox_exec.py"
)
PREAMBLE_MODULE = Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "_preamble.py"


def _load_module(path: Path, module_name: str):
    """Import a Python module from an explicit file path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sandbox_module_exists():
    """The sandbox MCP server module exists."""
    assert SANDBOX_MODULE.exists()


def test_sandbox_exec_module_exists():
    """The shared sandbox execution module exists."""
    assert SANDBOX_EXEC_MODULE.exists()


def test_sandbox_has_run_python_tool():
    """The sandbox module defines a run_python function."""
    content = SANDBOX_MODULE.read_text()
    assert "def run_python" in content
    assert "@mcp.tool()" in content


def test_sandbox_imports_shared_module():
    """The sandbox module imports from the shared _sandbox_exec module."""
    content = SANDBOX_MODULE.read_text()
    assert "from _sandbox_exec import" in content
    assert "check_code_safety" in content
    assert "run_sandboxed" in content


def test_sandbox_preamble_has_imports():
    """The preamble pre-imports expected libraries."""
    content = PREAMBLE_MODULE.read_text()
    assert "import pandas as pd" in content
    assert "import numpy as np" in content
    assert "import plotly.express as px" in content
    assert "import plotly.graph_objects as go" in content
    assert "import duckdb as _duckdb" in content
    assert "del _duckdb" in content


def test_sandbox_preamble_has_query_helper():
    """The preamble defines a query() shorthand."""
    content = PREAMBLE_MODULE.read_text()
    assert "def query(sql" in content
    assert "conn.execute(sql).fetchdf()" in content


def test_sandbox_preamble_uses_safe_conn_wrapper():
    """The preamble exposes a safe SQL wrapper instead of a raw connection."""
    content = PREAMBLE_MODULE.read_text()
    assert "class _SafeConn" in content
    assert "from _safety import ReadOnlyGuard as _ReadOnlyGuard" in content
    assert "_READ_ONLY_GUARD.wrap_with_limit(sql, max_rows=_READ_ONLY_MAX_ROWS)" in content


def test_sandbox_preamble_has_metric_calculator():
    """The preamble makes the metric_calculator module available."""
    content = PREAMBLE_MODULE.read_text()
    assert "import metric_calculator as mc" in content


def test_sandbox_preamble_uses_safe_interpolation():
    """The preamble uses repr() instead of str.format() to avoid injection."""
    content = PREAMBLE_MODULE.read_text()
    # The actual interpolation must use repr(), not .format(db_path=...)
    assert ".format(db_path=" not in content
    assert "repr(db_path)" in content
    assert "repr(skills_dir)" in content


def test_sandbox_exec_has_timeout():
    """The shared execution module enforces a timeout."""
    content = SANDBOX_EXEC_MODULE.read_text()
    assert "timeout=" in content
    assert "TimeoutExpired" in content


def test_sandbox_exec_detects_plotly_output():
    """The shared module detects plotly JSON in stdout."""
    content = SANDBOX_EXEC_MODULE.read_text()
    assert '"data" in parsed and "layout" in parsed' in content


def test_sandbox_exec_detects_dataframe_output():
    """The shared module detects DataFrame JSON (split orient) in stdout."""
    content = SANDBOX_EXEC_MODULE.read_text()
    assert '"columns" in parsed and "data" in parsed' in content


def test_sandbox_exec_cleans_up_temp_files():
    """The shared module removes temp script files after execution."""
    content = SANDBOX_EXEC_MODULE.read_text()
    assert "os.unlink(script_path)" in content
    assert "contextlib.suppress(OSError)" in content


def test_sandbox_exec_restricts_file_permissions():
    """The shared module sets temp file permissions to 0o600."""
    content = SANDBOX_EXEC_MODULE.read_text()
    assert "os.chmod(script_path, 0o600)" in content


def test_sandbox_exec_blocks_file_access_attributes():
    """The shared module blocks library-mediated file access helpers."""
    content = SANDBOX_EXEC_MODULE.read_text()
    assert "_BLOCKED_ATTRIBUTE_CALLS" in content
    assert "read_csv" in content
    assert "write_text" in content


class TestSandboxRuntimeIsolation:
    """Runtime tests for sandbox namespace and DuckDB escape prevention."""

    @pytest.fixture(autouse=True)
    def _load_modules(self):
        self.sandbox_exec = _load_module(SANDBOX_EXEC_MODULE, "_sandbox_exec_runtime")
        self.preamble_mod = _load_module(PREAMBLE_MODULE, "_preamble_runtime")

    def _run_with_preamble(self, tmp_path: Path, code: str) -> dict:
        db_path = tmp_path / "nba.duckdb"
        __import__("duckdb").connect(str(db_path)).close()
        skills_dir = (
            Path(__file__).resolve().parents[3]
            / "apps"
            / "chat"
            / "skills"
            / "nba-data-analytics"
            / "scripts"
        )
        session_dir = tmp_path / "session" / "sandbox-test"
        preamble = self.preamble_mod.build_preamble(
            str(db_path),
            str(skills_dir),
            str(session_dir),
        )
        return self.sandbox_exec.run_sandboxed(preamble + "\n" + code, cwd=tmp_path)

    def test_preamble_hides_internal_modules_and_raw_connection(self, tmp_path: Path):
        if not _HAS_PLOTLY:
            pytest.skip("plotly not installed")
        result = self._run_with_preamble(
            tmp_path,
            textwrap.dedent(
                """
                hidden = sorted(
                    name
                    for name in ("sys", "_io", "_b64", "_db_conn", "_RAW_CONN")
                    if name in globals()
                )
                print(json.dumps(hidden))
                """
            ),
        )

        assert result["stdout"] == "[]"

    def test_query_helper_still_works_after_namespace_cleanup(self, tmp_path: Path):
        if not _HAS_PLOTLY:
            pytest.skip("plotly not installed")
        result = self._run_with_preamble(
            tmp_path,
            textwrap.dedent(
                """
                print(query("SELECT 1 AS value").iloc[0, 0])
                """
            ),
        )

        assert result["stdout"] == "1"

    def test_query_helper_supports_explain_after_shared_guard_wrap_fix(self, tmp_path: Path):
        if not _HAS_PLOTLY:
            pytest.skip("plotly not installed")
        result = self._run_with_preamble(
            tmp_path,
            textwrap.dedent(
                """
                print(query("EXPLAIN SELECT 1").shape[0])
                """
            ),
        )

        assert result["stdout"] == "1"

    def test_preamble_does_not_expose_raw_duckdb(self, tmp_path: Path):
        db_path = tmp_path / "nba.duckdb"
        __import__("duckdb").connect(str(db_path)).close()
        full_code = textwrap.dedent(
            f"""
            import duckdb as _duckdb
            _db_conn = _duckdb.connect({str(db_path)!r}, read_only=True)
            _db_conn.execute("SET enable_external_access = false")
            del _duckdb
            print('duckdb' in globals())
            """
        )

        result = self.sandbox_exec.run_sandboxed(full_code, cwd=tmp_path)

        assert result["stdout"] == "False"

    def test_duckdb_sql_payload_cannot_read_local_files(self, tmp_path: Path):
        db_path = tmp_path / "nba.duckdb"
        __import__("duckdb").connect(str(db_path)).close()
        secret_path = tmp_path / "secret.csv"
        secret_path.write_text("top_secret\nvery-secret-value\n")
        full_code = textwrap.dedent(
            f"""
            import duckdb as _duckdb
            _db_conn = _duckdb.connect({str(db_path)!r}, read_only=True)
            _db_conn.execute("SET enable_external_access = false")
            del _duckdb
            try:
                print(
                    duckdb.sql(
                        "select * from read_csv_auto('{secret_path.as_posix()}')"
                    ).fetchall()
                )
            except Exception as exc:
                print(type(exc).__name__)
                print(str(exc))
            """
        )

        result = self.sandbox_exec.run_sandboxed(full_code, cwd=tmp_path)

        assert "NameError" in result["stdout"]
        assert "very-secret-value" not in result["stdout"]


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


class TestASTCodeSafety:
    """Test the AST-based code safety checker in _sandbox_exec.py."""

    @pytest.fixture(autouse=True)
    def _load_checker(self):
        """Import check_code_safety from the shared module."""
        mod = _load_module(SANDBOX_EXEC_MODULE, "_sandbox_exec_checker")
        self.check = mod.check_code_safety

    def test_blocks_subprocess_import(self):
        assert self.check("import subprocess") is not None

    def test_blocks_os_import(self):
        assert self.check("import os") is not None

    def test_blocks_os_submodule(self):
        assert self.check("from os import path") is not None

    def test_blocks_shutil_import(self):
        assert self.check("import shutil") is not None

    def test_blocks_importlib(self):
        assert self.check("import importlib") is not None

    def test_blocks_exec_call(self):
        assert self.check('exec("print(1)")') is not None

    def test_blocks_eval_call(self):
        assert self.check('eval("1+1")') is not None

    def test_blocks_open_call(self):
        assert self.check('open("/etc/passwd")') is not None

    def test_blocks_dunder_import(self):
        assert self.check('__import__("subprocess")') is not None

    def test_blocks_getattr_call(self):
        assert self.check('getattr(obj, "system")') is not None

    def test_blocks_builtins_import(self):
        assert self.check("import builtins") is not None

    def test_allows_pandas(self):
        assert self.check("import pandas as pd") is None

    def test_allows_numpy(self):
        assert self.check("import numpy as np") is None

    def test_allows_plotly(self):
        assert self.check("import plotly.express as px") is None

    def test_blocks_pandas_read_csv_call(self):
        assert self.check("pd.read_csv('/tmp/data.csv')") is not None

    def test_blocks_path_read_text_call(self):
        assert self.check("some_path.read_text()") is not None

    def test_blocks_duckdb_connect_call(self):
        assert self.check("duckdb.connect('/tmp/test.duckdb')") is not None

    def test_blocks_duckdb_import(self):
        assert self.check("import duckdb") is not None

    def test_blocks_duckdb_sql_call(self):
        assert self.check("duckdb.sql('select 1')") is not None

    def test_blocks_duckdb_execute_call(self):
        assert self.check("duckdb.execute('select 1')") is not None

    def test_blocks_duckdb_query_call(self):
        assert self.check("duckdb.query('select 1')") is not None

    def test_allows_print(self):
        assert self.check('print("hello")') is None

    def test_allows_json(self):
        assert self.check("import json; json.dumps({})") is None

    def test_allows_scipy(self):
        assert self.check("import scipy.stats as stats") is None

    def test_allows_matplotlib(self):
        assert self.check("import matplotlib.pyplot as plt") is None

    def test_blocks_exec_string_concat_bypass(self):
        """exec() with string concatenation to bypass old blocklist."""
        assert self.check('exec("import subp" + "rocess")') is not None

    def test_blocks_double_quote_import(self):
        """__import__ with double quotes (old blocklist only caught single quotes)."""
        assert self.check('__import__("subprocess")') is not None

    def test_reports_syntax_error(self):
        result = self.check("def oops(")
        assert result is not None
        assert "Syntax error" in result

    def test_allows_basic_computation(self):
        code = "x = [1, 2, 3]\ny = sum(x)\nprint(y)"
        assert self.check(code) is None

    def test_allows_query_helper(self):
        """query() is a preamble-defined helper, should be allowed."""
        assert self.check('df = query("SELECT 1")') is None

    # --- Additional blocked modules (Wave 1 extensions) ---

    def test_blocks_signal(self):
        assert self.check("import signal") is not None

    def test_blocks_multiprocessing(self):
        assert self.check("import multiprocessing") is not None

    def test_blocks_threading(self):
        assert self.check("import threading") is not None

    def test_blocks_ctypes(self):
        assert self.check("import ctypes") is not None

    def test_blocks_socket(self):
        assert self.check("import socket") is not None

    def test_blocks_http(self):
        assert self.check("from http import client") is not None

    def test_blocks_urllib(self):
        assert self.check("import urllib.request") is not None

    def test_allows_plotly_express(self):
        assert self.check("import plotly.express as px") is None

    def test_allows_plotly_go(self):
        assert self.check("import plotly.graph_objects as go") is None

    def test_blocks_compile_call(self):
        assert self.check('compile("print(1)", "<>", "exec")') is not None

    def test_blocks_breakpoint(self):
        assert self.check("breakpoint()") is not None

    def test_blocks_setattr(self):
        assert self.check('setattr(obj, "attr", val)') is not None

    def test_blocks_delattr(self):
        assert self.check('delattr(obj, "attr")') is not None

    def test_allows_list_comprehension(self):
        assert self.check("[x*2 for x in range(10)]") is None

    def test_allows_f_string(self):
        assert self.check('name = "LeBron"; print(f"{name}")') is None

    # --- Blocked dunder attributes (audit fix: CVE-2026-27577) ---

    def test_blocks_objclass_access(self):
        assert self.check("x.__objclass__") is not None

    def test_blocks_reduce_access(self):
        assert self.check("x.__reduce__") is not None

    def test_blocks_reduce_ex_access(self):
        assert self.check("x.__reduce_ex__") is not None

    def test_blocks_init_subclass_access(self):
        assert self.check("x.__init_subclass__") is not None

    def test_blocks_set_name_access(self):
        assert self.check("x.__set_name__") is not None

    def test_blocks_class_getitem_access(self):
        assert self.check("x.__class_getitem__") is not None

    # --- Decorator expression guard ---

    def test_blocks_eval_in_decorator(self):
        code = "@eval(\"__import__('os')\")\ndef f(): pass"
        assert self.check(code) is not None

    def test_blocks_exec_in_decorator(self):
        code = '@exec("import os")\ndef f(): pass'
        assert self.check(code) is not None

    def test_blocks_compile_in_decorator(self):
        code = '@compile("x", "<>", "exec")\ndef f(): pass'
        assert self.check(code) is not None

    def test_allows_safe_decorator(self):
        code = "@property\ndef x(self): return 1"
        assert self.check(code) is None


class TestEnvScrubbing:
    """Test that the shared module scrubs sensitive env vars."""

    def test_shared_module_scrubs_env_vars(self):
        """The shared execution module filters sensitive env vars."""
        content = SANDBOX_EXEC_MODULE.read_text()
        assert "build_clean_env" in content
        assert "API_KEY" in content
        assert "SECRET" in content
        assert "TOKEN" in content
        assert "PASSWORD" in content

    def test_sandbox_uses_shared_scrubbing(self):
        """sandbox.py delegates to the shared module for execution."""
        content = SANDBOX_MODULE.read_text()
        assert "run_sandboxed" in content


class TestProcessIsolation:
    """Test that the shared module uses process group isolation."""

    def test_shared_module_uses_new_session(self):
        """The shared module uses start_new_session=True."""
        content = SANDBOX_EXEC_MODULE.read_text()
        assert "start_new_session=True" in content
