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

    # --- __dict__ / introspection dunder attrs (round 2 audit) ---

    def test_blocks_dict_attr(self):
        assert self.check("x.__dict__") is not None

    def test_blocks_defaults_attr(self):
        assert self.check("f.__defaults__") is not None

    def test_blocks_func_attr(self):
        assert self.check("m.__func__") is not None

    def test_blocks_closure_attr(self):
        assert self.check("f.__closure__") is not None

    def test_blocks_wrapped_attr(self):
        assert self.check("f.__wrapped__") is not None

    def test_blocks_self_attr(self):
        assert self.check("m.__self__") is not None

    def test_blocks_builtins_dict_subscript(self):
        """__builtins__.__dict__["open"] bypass vector."""
        code = '__builtins__.__dict__["open"]("/etc/passwd")'
        assert self.check(code) is not None

    def test_blocks_bare_builtins_access(self):
        """Bare __builtins__ name access (subscript bypass enabler)."""
        assert self.check("x = __builtins__") is not None

    # --- numpy/plotly file I/O bypass (round 2 audit) ---

    def test_blocks_np_save(self):
        assert self.check('np.save("/tmp/d.npy", arr)') is not None

    def test_blocks_np_load(self):
        assert self.check('np.load("/tmp/d.npy")') is not None

    def test_blocks_np_loadtxt(self):
        assert self.check('np.loadtxt("/etc/passwd")') is not None

    def test_blocks_np_genfromtxt(self):
        assert self.check('np.genfromtxt("/etc/passwd")') is not None

    def test_blocks_np_fromfile(self):
        assert self.check('np.fromfile("/etc/passwd")') is not None

    def test_blocks_np_savetxt(self):
        assert self.check('np.savetxt("/tmp/o.txt", arr)') is not None

    def test_blocks_write_html(self):
        assert self.check('fig.write_html("/tmp/x.html")') is not None

    def test_blocks_write_image(self):
        assert self.check('fig.write_image("/tmp/x.png")') is not None

    def test_blocks_write_json_plotly(self):
        assert self.check('fig.write_json("/tmp/x.json")') is not None

    def test_allows_safe_numpy_ops(self):
        """Common numpy operations must still work."""
        assert self.check("x = np.mean([1, 2, 3])") is None
        assert self.check("arr = np.array([1, 2, 3])") is None
        assert self.check("y = np.std(arr)") is None

    # --- round 3 audit: blocked builtins ---

    def test_blocks_type_builtin(self):
        """type() 3-arg form is a sandbox escape primitive."""
        assert self.check('type("X", (object,), {})') is not None

    def test_blocks_help_builtin(self):
        """help() leaks function signatures including default args."""
        assert self.check("help(conn.execute)") is not None

    def test_blocks_dir_builtin(self):
        """dir() leaks namespace information."""
        assert self.check("dir(conn)") is not None

    def test_blocks_memoryview_builtin(self):
        """memoryview() allows raw memory access."""
        assert self.check("memoryview(b'abc')") is not None

    # --- honest-review: bare builtin reference aliasing ---

    def test_blocked_builtin_aliasing_import(self):
        """imp = __import__ must be blocked (not just __import__() calls)."""
        assert self.check("imp = __import__") is not None

    def test_blocked_builtin_aliasing_in_list(self):
        """[__import__][0] must be blocked."""
        assert self.check("imp = [__import__][0]") is not None

    def test_blocked_builtin_aliasing_eval(self):
        """ev = eval must be blocked."""
        assert self.check("ev = eval") is not None

    def test_blocked_builtin_aliasing_open(self):
        """op = open must be blocked."""
        assert self.check("op = open") is not None

    def test_allowed_name_not_blocked(self):
        """Normal names like pd, np, conn must still be allowed."""
        assert self.check("x = pd.DataFrame()") is None
        assert self.check("y = np.array([1, 2])") is None
        assert self.check("z = conn") is None

    # --- round 3 audit: descriptor dunders ---

    def test_blocks_getattr_dunder(self):
        assert self.check("x.__getattr__") is not None

    def test_blocks_getattribute_dunder(self):
        assert self.check("x.__getattribute__") is not None

    def test_blocks_setattr_dunder(self):
        assert self.check("x.__setattr__") is not None

    def test_blocks_delattr_dunder(self):
        assert self.check("x.__delattr__") is not None

    def test_blocks_get_descriptor(self):
        assert self.check("x.__get__") is not None

    def test_blocks_set_descriptor(self):
        assert self.check("x.__set__") is not None

    def test_blocks_delete_descriptor(self):
        assert self.check("x.__delete__") is not None

    # --- round 3 audit: savefig moved to calls-only ---

    def test_blocks_savefig_call(self):
        """savefig() call is blocked (file I/O)."""
        assert self.check('fig.savefig("/tmp/x.png")') is not None

    def test_allows_savefig_attr_access(self):
        """savefig attribute access (not a call) is allowed."""
        assert self.check("x = fig.savefig") is None

    # --- round 3 audit: SafeConn uses closures ---

    def test_safe_conn_uses_closures(self):
        """_SafeConn methods must NOT use default-arg capture (info leak via __defaults__)."""
        content = PREAMBLE_MODULE.read_text()
        assert "_executor=_safe_execute" not in content
        assert "_executor=_safe_sql" not in content
        assert "_raw_conn=_RAW_CONN" not in content


class TestEnvScrubbing:
    """Test that the shared module scrubs sensitive env vars."""

    @pytest.fixture(autouse=True)
    def _load_env_builder(self):
        mod = _load_module(SANDBOX_EXEC_MODULE, "_sandbox_exec_env")
        self.build_clean_env = mod.build_clean_env
        self.safe_vars = mod._SAFE_ENV_VARS

    def test_uses_allowlist_approach(self):
        """The env scrubber uses an allowlist, not a blocklist."""
        assert "PATH" in self.safe_vars
        assert "HOME" in self.safe_vars

    def test_blocks_api_keys(self, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "secret123")
        monkeypatch.setenv("PATH", "/usr/bin")
        env = self.build_clean_env()
        assert "MY_API_KEY" not in env
        assert "PATH" in env

    def test_blocks_database_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://...")
        env = self.build_clean_env()
        assert "DATABASE_URL" not in env

    def test_blocks_aws_credentials(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA...")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        env = self.build_clean_env()
        assert "AWS_ACCESS_KEY_ID" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env

    def test_passes_safe_vars(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/user")
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        monkeypatch.setenv("VIRTUAL_ENV", "/venv")
        env = self.build_clean_env()
        assert env.get("HOME") == "/home/user"
        assert env.get("LANG") == "en_US.UTF-8"
        assert env.get("VIRTUAL_ENV") == "/venv"

    def test_sandbox_uses_shared_scrubbing(self):
        """sandbox.py delegates to the shared module for execution."""
        content = SANDBOX_MODULE.read_text()
        assert "run_sandboxed" in content


class TestSessionIdSanitization:
    """Test that session IDs are sanitized to prevent path traversal."""

    def test_chainlit_app_sanitizes_session_id(self):
        """chainlit_app.py must use _sanitize_session_id."""
        app_path = Path(__file__).resolve().parents[3] / "apps" / "chat" / "chainlit_app.py"
        content = app_path.read_text()
        assert "_sanitize_session_id" in content

    def test_sandbox_mcp_sanitizes_session_id(self):
        """sandbox.py must sanitize the session ID from CLI args."""
        content = SANDBOX_MODULE.read_text()
        assert "re.sub" in content

    def test_cleanup_guards_path_traversal(self):
        """_cleanup_session_state must check is_relative_to before rmtree."""
        app_path = Path(__file__).resolve().parents[3] / "apps" / "chat" / "chainlit_app.py"
        content = app_path.read_text()
        assert "is_relative_to" in content

    def test_sanitize_strips_path_chars(self):
        """The sanitizer regex removes dots, slashes, and other path chars."""
        import re

        pattern = re.compile(r"[^a-zA-Z0-9_-]")

        def _sanitize(raw: str) -> str:
            return pattern.sub("", raw)[:128] or "default"

        assert _sanitize("../../etc/passwd") == "etcpasswd"
        assert _sanitize("normal-session_123") == "normal-session_123"
        assert _sanitize("") == "default"
        assert _sanitize("../..") == "default"  # all chars stripped → fallback
        result = _sanitize("../../../important")
        assert "/" not in result
        assert ".." not in result


class TestMultiOutput:
    """Test multi-output sandbox rendering support."""

    @pytest.fixture(autouse=True)
    def _load_parser(self):
        mod = _load_module(SANDBOX_EXEC_MODULE, "_sandbox_exec_multi")
        self.parse = mod._parse_structured_output
        self.parse_all = mod._parse_all_structured_outputs
        self.classify = mod._classify_output

    def test_single_dataframe_backward_compatible(self):
        """Single DataFrame output returns legacy format (no _multi wrapper)."""
        stdout = '{"columns": ["a", "b"], "data": [[1, 2], [3, 4]]}'
        result = self.parse(stdout, "")
        assert "columns" in result
        assert result["columns"] == ["a", "b"]
        assert "_multi" not in result

    def test_single_plotly_backward_compatible(self):
        """Single Plotly output returns legacy _raw format."""
        stdout = '{"data": [{"x": [1]}], "layout": {"title": "test"}}'
        result = self.parse(stdout, "")
        assert "_raw" in result
        assert "_multi" not in result

    def test_multi_output_table_and_chart(self):
        """Multiple structured outputs return _multi list."""
        table_line = '{"columns": ["x"], "data": [[1], [2]]}'
        chart_line = '{"data": [{"x": [1]}], "layout": {"title": "t"}}'
        stdout = f"{table_line}\n{chart_line}"
        result = self.parse(stdout, "")
        assert "_multi" in result
        assert len(result["_multi"]) == 2
        assert result["_multi"][0]["_type"] == "dataframe"
        assert result["_multi"][1]["_type"] == "plotly"

    def test_multi_output_preserves_plain_text(self):
        """Non-JSON lines are preserved as plain text."""
        stdout = 'Hello world\n{"columns": ["x"], "data": [[1]]}\nDone'
        result = self.parse(stdout, "")
        # Single structured output → no _multi
        assert "columns" in result
        # But if we test parse_all directly:
        results, plain = self.parse_all(stdout)
        assert len(results) == 1
        assert "Hello world" in plain
        assert "Done" in plain

    def test_classify_matplotlib(self):
        """Matplotlib output is correctly classified."""
        parsed = {"image_base64": "abc", "format": "png"}
        result = self.classify(parsed)
        assert result["_type"] == "matplotlib"

    def test_classify_export(self):
        """Export outputs (csv, embed, etc.) are correctly classified."""
        parsed = {"format": "csv", "content": "base64data", "export_file": "out.csv"}
        result = self.classify(parsed)
        assert result["_type"] == "csv"

    def test_classify_unknown_returns_none(self):
        """Unknown dict structure returns None."""
        assert self.classify({"random": "stuff"}) is None

    def test_empty_stdout(self):
        """Empty stdout returns plain stdout/stderr dict."""
        result = self.parse("", "some warning")
        assert result == {"stdout": "", "stderr": "some warning"}


class TestProcessIsolation:
    """Test that the shared module uses process group isolation."""

    def test_shared_module_uses_new_session(self):
        """The shared module uses start_new_session=True."""
        content = SANDBOX_EXEC_MODULE.read_text()
        assert "start_new_session=True" in content

    def test_no_preexec_fn(self):
        """preexec_fn is NOT used (deprecated and conflicts with start_new_session)."""
        content = SANDBOX_EXEC_MODULE.read_text()
        assert "preexec_fn" not in content

    def test_resource_limits_code_constant_exists(self):
        """_RESOURCE_LIMITS_CODE string constant exists in the module."""
        content = SANDBOX_EXEC_MODULE.read_text()
        assert "_RESOURCE_LIMITS_CODE" in content

    def test_resource_limits_code_contains_rlimit_cpu(self):
        """Resource limits include RLIMIT_CPU."""
        content = SANDBOX_EXEC_MODULE.read_text()
        assert "RLIMIT_CPU" in content

    def test_resource_limits_code_contains_rlimit_nproc(self):
        """Resource limits include RLIMIT_NPROC to prevent forking."""
        content = SANDBOX_EXEC_MODULE.read_text()
        assert "RLIMIT_NPROC" in content
