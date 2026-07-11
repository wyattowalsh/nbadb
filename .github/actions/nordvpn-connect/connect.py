from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Final


class ActionError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


AUTH_FAILURE_PATTERN: Final[re.Pattern[str]] = re.compile(r"AUTH_FAILED|auth-failure")
INIT_COMPLETE_PATTERN: Final[str] = "Initialization Sequence Completed"
NBA_PROBE_DEFAULT_URL: Final[str] = "https://stats.nba.com/stats/commonteamyears?LeagueID=00"
NBA_PROBE_MAX_BYTES: Final[int] = 1_048_576
NBA_PROBE_EXPECTED_HEADERS: Final[frozenset[str]] = frozenset(
    {"LEAGUE_ID", "TEAM_ID", "MIN_YEAR", "MAX_YEAR", "ABBREVIATION"}
)
NBA_PROBE_TERMINATION_GRACE_SECONDS: Final[float] = 0.25
NBA_STACK_PROBE_DEFAULT_SEASON: Final[str] = "2024-25"
NBA_STACK_PROBE_DIAGNOSTIC_MAX_CHARS: Final[int] = 240
NBA_STACK_PROBE_ENDPOINTS: Final[frozenset[str]] = frozenset(
    {"common_all_players", "league_game_log"}
)
NBA_STACK_PROBE_TRANSPORT_ERROR_TYPES: Final[frozenset[str]] = frozenset(
    {
        "ConnectTimeout",
        "ConnectionError",
        "HTTPError",
        "ReadTimeout",
        "Timeout",
        "TimeoutError",
        "TransientError",
    }
)
NBA_STACK_PROBE_CONTRACT_ERROR_TYPES: Final[frozenset[str]] = frozenset(
    {
        "ExtractionError",
        "JSONDecodeError",
        "NbaDbValidationError",
        "ProbeContractError",
        "ValidationError",
    }
)
NBA_STACK_PROBE_RUNTIME_ERROR_TYPES: Final[frozenset[str]] = frozenset(
    {
        "AttributeError",
        "ImportError",
        "ModuleNotFoundError",
        "RuntimeError",
        "TypeError",
    }
)
NBA_STACK_PROBE_ERROR_TYPES: Final[frozenset[str]] = (
    NBA_STACK_PROBE_TRANSPORT_ERROR_TYPES
    | NBA_STACK_PROBE_CONTRACT_ERROR_TYPES
    | NBA_STACK_PROBE_RUNTIME_ERROR_TYPES
)
NBA_STACK_PROBE_FAILURE_KINDS: Final[frozenset[str]] = frozenset(
    {"empty", "exception", "invalid_values", "missing_columns"}
)
NBA_PROBE_HEADERS: Final[tuple[tuple[str, str], ...]] = (
    ("Accept", "application/json, text/plain, */*"),
    ("Accept-Language", "en-US,en;q=0.5"),
    ("Cache-Control", "no-cache"),
    ("Connection", "keep-alive"),
    ("Pragma", "no-cache"),
    ("Referer", "https://www.nba.com/"),
    (
        "User-Agent",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    ),
)


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        raw = str(default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ActionError(
            "vpn_network_error",
            f"{name} must be an integer, got {raw!r}",
        ) from exc
    if minimum is not None and value < minimum:
        raise ActionError(
            "vpn_network_error",
            f"{name} must be >= {minimum}, got {value}",
        )
    return value


def write_output(key: str, value: object) -> None:
    output_path = os.environ["GITHUB_OUTPUT"]
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def run_command(
    cmd: list[str],
    *,
    timeout: float | None = None,
    capture_output: bool = True,
    check: bool = False,
    termination_grace: float = 5.0,
) -> subprocess.CompletedProcess[str]:
    stdout_target: int = subprocess.PIPE if capture_output else subprocess.DEVNULL
    stderr_target: int = subprocess.PIPE if capture_output else subprocess.DEVNULL
    process = subprocess.Popen(
        cmd,
        text=True,
        stdout=stdout_target,
        stderr=stderr_target,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        termination_grace = max(0.05, termination_grace)
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=termination_grace)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=termination_grace)
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=timeout if timeout is not None else 0.0,
            output=stdout or exc.output,
            stderr=stderr or exc.stderr,
        ) from exc

    completed = subprocess.CompletedProcess(
        cmd,
        process.returncode,
        stdout,
        stderr,
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            cmd,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def run_quiet(cmd: list[str], *, timeout: float | None = None) -> None:
    with suppress(subprocess.TimeoutExpired, OSError):
        run_command(
            cmd,
            check=False,
            timeout=timeout,
            capture_output=False,
        )


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_quarantined_servers(raw: str) -> tuple[str, ...]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ActionError(
            "vpn_network_error",
            f"invalid quarantined-servers-json input: {exc}",
        ) from exc
    if not isinstance(payload, list):
        raise ActionError(
            "vpn_network_error",
            "quarantined-servers-json must decode to a JSON array",
        )
    seen: set[str] = set()
    values: list[str] = []
    for value in payload:
        hostname = str(value).strip()
        if not hostname or hostname in seen:
            continue
        seen.add(hostname)
        values.append(hostname)
    return tuple(values)


class NordVpnConnectAction:
    def __init__(self) -> None:
        self.runner_temp = Path(os.environ["RUNNER_TEMP"])
        self.work_dir = self.runner_temp / "nordvpn"
        self.log_file = self.work_dir / "openvpn.log"
        self.pid_file = self.work_dir / "openvpn.pid"
        self.creds_file = self.work_dir / "nordvpn-creds.json"
        self.servers_file = self.work_dir / "nordvpn-servers.json"
        self.verify_file = self.work_dir / "vpn-exit-ip.json"
        self.nba_probe_file = self.work_dir / "nba-stats-probe.json"
        self.nba_stack_probe_script = (
            Path(__file__).resolve().parents[2] / "scripts" / "probe_discovery_transport.py"
        )
        self.project_root = Path(
            os.environ.get("GITHUB_WORKSPACE", "") or self.nba_stack_probe_script.parents[2]
        ).resolve()
        self.baseline_file = self.work_dir / "baseline-ip.json"
        self.auth_file = self.work_dir / "vpn-auth.txt"
        self.token_auth_file = self.work_dir / "nordvpn-token.netrc"

        self.selector_index = env_int("LANE_INDEX", env_int("SHARD_INDEX", 0), minimum=0)
        self.server_limit = env_int("SERVER_LIMIT", 4, minimum=1)
        self.connect_timeout = env_int("CONNECT_TIMEOUT_SECONDS", 90, minimum=30)
        self.overall_timeout = env_int("OVERALL_TIMEOUT_SECONDS", 300, minimum=30)
        self.auth_rejection_limit = env_int("AUTH_REJECTION_LIMIT", 3, minimum=1)
        self.auth_recovery_rounds = env_int("AUTH_RECOVERY_ROUNDS", 2, minimum=0)
        self.auth_recovery_base_delay = env_int("AUTH_RECOVERY_BASE_DELAY_SECONDS", 10, minimum=0)
        if self.overall_timeout < self.connect_timeout:
            raise ActionError(
                "vpn_network_error",
                "OVERALL_TIMEOUT_SECONDS must be >= CONNECT_TIMEOUT_SECONDS",
            )
        self.deadline = time.monotonic() + self.overall_timeout

        self.country_id = os.environ.get("COUNTRY_ID", "228").strip() or "228"
        self.technology = os.environ.get("TECHNOLOGY", "openvpn_udp").strip() or "openvpn_udp"
        self.fallback_technology = os.environ.get("FALLBACK_TECHNOLOGY", "openvpn_tcp").strip()
        self.verify_url = os.environ.get("VERIFY_URL", "https://api.ipify.org?format=json").strip()
        self.require_full_tunnel = (
            os.environ.get("REQUIRE_FULL_TUNNEL", "true").strip().lower() == "true"
        )
        self.nba_probe_enabled = (
            os.environ.get("NBA_PROBE_ENABLED", "true").strip().lower() != "false"
        )
        self.nba_probe_url = (
            os.environ.get("NBA_PROBE_URL", NBA_PROBE_DEFAULT_URL).strip() or NBA_PROBE_DEFAULT_URL
        )
        self.nba_probe_timeout = env_int("NBA_PROBE_TIMEOUT_SECONDS", 10, minimum=1)
        self.nba_stack_probe_enabled = (
            os.environ.get("NBA_STACK_PROBE_ENABLED", "true").strip().lower() != "false"
        )
        self.nba_stack_probe_timeout = env_int("NBA_STACK_PROBE_TIMEOUT_SECONDS", 18, minimum=2)
        self.nba_stack_probe_season = (
            os.environ.get("NBA_STACK_PROBE_SEASON", NBA_STACK_PROBE_DEFAULT_SEASON).strip()
            or NBA_STACK_PROBE_DEFAULT_SEASON
        )
        self.quarantined_servers = parse_quarantined_servers(
            os.environ.get("QUARANTINED_SERVERS_JSON", "[]")
        )
        self.require_token_auth = (
            os.environ.get("REQUIRE_TOKEN_AUTH", "false").strip().lower() == "true"
        )
        self.configured_auth_prevalidated = (
            os.environ.get("CONFIGURED_AUTH_PREVALIDATED", "false").strip().lower() == "true"
        )

        self.status = "vpn_network_error"
        self.baseline_ip = ""
        self.exit_ip = ""
        self.interface = ""
        self.server = ""
        self.pid = ""
        self.attempted_servers: list[str] = []
        self.failed_servers: list[str] = []
        self.openvpn_process: subprocess.Popen[str] | None = None
        self.auth_source = ""
        self.auth_validated = self.configured_auth_prevalidated
        self.last_attempt_auth_failed = False
        self.technology_selection_offsets: dict[str, int] = {}
        self.technology_cursor = 0
        probes_enabled = self.nba_probe_enabled or self.nba_stack_probe_enabled
        self.nba_probe_status = "not_run" if probes_enabled else "disabled"
        self.nba_probe_diagnostic = (
            "NBA probes have not run" if probes_enabled else "NBA probes disabled by configuration"
        )
        self.verification_failure = ""

    def remaining_budget(self) -> float:
        return self.deadline - time.monotonic()

    def ensure_budget(self, label: str, *, minimum: float = 5.0) -> None:
        if self.remaining_budget() <= minimum:
            raise ActionError(
                "vpn_connect_timeout",
                f"{label} skipped because the VPN connection budget is exhausted",
            )

    def command_timeout(self, *, cap: float) -> float:
        self.ensure_budget("command")
        return max(1.0, min(cap, self.remaining_budget()))

    def sleep_with_budget(
        self,
        label: str,
        seconds: float,
        *,
        minimum_after: float = 5.0,
    ) -> bool:
        if self.remaining_budget() <= seconds + minimum_after:
            print(
                f"::warning::Skipping {label.lower()} because it would leave less than "
                f"{self.format_seconds(minimum_after)}s for the next operation"
            )
            return False
        if seconds <= 0:
            return True
        print(f"::notice::{label}; waiting {self.format_seconds(seconds)}s")
        time.sleep(seconds)
        return True

    def append_unique(self, values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    def probe_remaining_budget(self, attempt_deadline: float | None) -> float:
        remaining = self.remaining_budget()
        if attempt_deadline is not None:
            remaining = min(remaining, attempt_deadline - time.monotonic())
        return remaining

    def probe_time_limits(
        self,
        configured_timeout: float,
        attempt_deadline: float | None,
    ) -> tuple[float, float] | None:
        remaining = self.probe_remaining_budget(attempt_deadline)
        cleanup_budget = NBA_PROBE_TERMINATION_GRACE_SECONDS * 2
        if remaining <= cleanup_budget + 0.5:
            return None
        process_limit = min(float(configured_timeout) + 0.25, remaining - cleanup_budget)
        request_limit = min(float(configured_timeout), max(0.5, process_limit - 0.25))
        return request_limit, process_limit

    def helper_timeout(
        self,
        *,
        cap: float,
        attempt_deadline: float | None,
    ) -> float | None:
        remaining = self.probe_remaining_budget(attempt_deadline)
        cleanup_budget = NBA_PROBE_TERMINATION_GRACE_SECONDS * 2
        if remaining <= cleanup_budget + 0.1:
            return None
        return min(cap, remaining - cleanup_budget)

    @staticmethod
    def format_seconds(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def make_workdir_readable(self) -> None:
        if not self.work_dir.is_dir():
            return
        run_quiet(["sudo", "chmod", "a+rx", str(self.work_dir)], timeout=10)
        private_paths = {self.auth_file, self.creds_file, self.token_auth_file}
        for path in self.work_dir.iterdir():
            if path in private_paths:
                run_quiet(["sudo", "chmod", "600", str(path)], timeout=10)
            else:
                run_quiet(["sudo", "chmod", "a+rX", str(path)], timeout=10)

    def cleanup_sensitive(self) -> None:
        for path in (
            self.creds_file,
            self.token_auth_file,
            self.servers_file,
            self.verify_file,
            self.nba_probe_file,
            self.baseline_file,
        ):
            with suppress(FileNotFoundError):
                path.unlink()
        if self.status != "connected":
            with suppress(FileNotFoundError):
                self.auth_file.unlink()

    def cleanup_openvpn(self) -> None:
        if self.openvpn_process is not None:
            with suppress(ProcessLookupError):
                os.killpg(self.openvpn_process.pid, signal.SIGTERM)
            try:
                self.openvpn_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(self.openvpn_process.pid, signal.SIGKILL)
                with suppress(subprocess.TimeoutExpired):
                    self.openvpn_process.wait(timeout=5)
            self.openvpn_process = None
        pid = ""
        if self.pid_file.exists():
            pid = self.pid_file.read_text(encoding="utf-8", errors="replace").strip()
        if pid:
            run_quiet(["sudo", "kill", pid], timeout=10)
            time.sleep(2)
            run_quiet(["sudo", "kill", "-9", pid], timeout=10)
        with suppress(FileNotFoundError):
            self.pid_file.unlink()

    def retry_http_get(
        self,
        label: str,
        output_path: Path,
        url: str,
        *extra_args: str,
        attempt_deadline: float | None = None,
        request_timeout: float = 30.0,
        non_retryable_http_codes: frozenset[str] = frozenset(),
    ) -> bool:
        attempts = 3
        for attempt in range(1, attempts + 1):
            self.ensure_budget(label)
            limits = self.probe_time_limits(request_timeout, attempt_deadline)
            if limits is None:
                print(f"::error::{label} skipped because the server-attempt budget is exhausted")
                return False
            request_limit, process_limit = limits
            request_timeout_text = self.format_seconds(request_limit)
            connect_timeout_text = self.format_seconds(min(10.0, request_limit))
            cmd = [
                "curl",
                "-sS",
                "--connect-timeout",
                connect_timeout_text,
                "--max-time",
                request_timeout_text,
                "-o",
                str(output_path),
                "-w",
                "%{http_code}",
                *extra_args,
                url,
            ]
            try:
                result = run_command(
                    cmd,
                    timeout=process_limit,
                    capture_output=True,
                    check=False,
                    termination_grace=NBA_PROBE_TERMINATION_GRACE_SECONDS,
                )
            except subprocess.TimeoutExpired:
                result = None

            ok = False
            status_text = "timeout"
            if result is not None:
                http_code = (result.stdout or "").strip()
                if result.returncode == 0 and http_code.startswith("2"):
                    ok = True
                elif result.returncode != 0:
                    status_text = f"curl exit {result.returncode}"
                else:
                    status_text = f"HTTP {http_code or 'unknown'}"

            if ok:
                return True
            if result is not None and http_code in non_retryable_http_codes:
                print(f"::error::{label} failed ({status_text}); response is not retryable")
                return False
            if attempt == attempts:
                print(f"::error::{label} failed after {attempt} attempts ({status_text})")
                return False
            sleep_for = attempt * 5
            if self.probe_remaining_budget(attempt_deadline) <= sleep_for + 1.0:
                print(
                    f"::error::{label} failed ({status_text}) and retrying would "
                    "exceed the current operation budget"
                )
                return False
            print(
                f"::warning::{label} failed ({status_text}); retrying in "
                f"{sleep_for}s ({attempt}/{attempts})"
            )
            time.sleep(sleep_for)
        return False

    def auth_failed_in_log(self) -> bool:
        return AUTH_FAILURE_PATTERN.search(read_text(self.log_file)) is not None

    def initialization_complete(self) -> bool:
        return INIT_COMPLETE_PATTERN in read_text(self.log_file)

    def get_interface(self, *, attempt_deadline: float | None = None) -> str:
        timeout = self.helper_timeout(cap=10.0, attempt_deadline=attempt_deadline)
        if timeout is None:
            return ""
        try:
            result = run_command(
                ["ip", "-o", "link", "show"],
                timeout=timeout,
                termination_grace=NBA_PROBE_TERMINATION_GRACE_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return ""
        for line in (result.stdout or "").splitlines():
            match = re.search(r": (tun\d+):", line)
            if match:
                return match.group(1)
        return ""

    def route_uses_interface(
        self,
        route_expr: str,
        interface: str,
        *,
        attempt_deadline: float | None = None,
    ) -> bool:
        timeout = self.helper_timeout(cap=10.0, attempt_deadline=attempt_deadline)
        if timeout is None:
            return False
        try:
            result = run_command(
                ["ip", "route", "show", route_expr],
                timeout=timeout,
                termination_grace=NBA_PROBE_TERMINATION_GRACE_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return False
        return f" dev {interface}" in (result.stdout or "")

    def pid_alive(self, pid: str, *, attempt_deadline: float | None = None) -> bool:
        timeout = self.helper_timeout(cap=10.0, attempt_deadline=attempt_deadline)
        if timeout is None:
            return False
        try:
            result = run_command(
                ["sudo", "kill", "-0", pid],
                timeout=timeout,
                capture_output=False,
                check=False,
                termination_grace=NBA_PROBE_TERMINATION_GRACE_SECONDS,
            )
        except (subprocess.TimeoutExpired, OSError):
            print(
                "::warning::Timed out while probing the OpenVPN process; "
                "treating the process as unhealthy"
            )
            return False
        return result.returncode == 0

    def prepare_workdir(self) -> None:
        run_quiet(["rm", "-rf", str(self.work_dir)], timeout=10)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.chmod(0o700)
        write_output("work-dir", self.work_dir)
        write_output("log-file", self.log_file)
        write_output("pid-file", self.pid_file)

    def install_dependencies(self) -> None:
        if shutil.which("jq") and shutil.which("openvpn"):
            print("::notice::OpenVPN dependencies already available on the runner")
            return

        print("::notice::Preparing OpenVPN dependencies")
        for label, cmd in (
            ("apt-get update", ["sudo", "apt-get", "update", "-qq"]),
            ("apt-get install", ["sudo", "apt-get", "install", "-y", "-qq", "jq", "openvpn"]),
        ):
            last_timeout: subprocess.TimeoutExpired | None = None
            for attempt in range(1, 3):
                try:
                    result = run_command(
                        cmd,
                        timeout=self.command_timeout(cap=120),
                        capture_output=True,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    last_timeout = exc
                    result = None
                if result is not None and result.returncode == 0:
                    break
                if attempt < 2 and self.remaining_budget() > 30:
                    print(
                        f"::warning::{label} did not complete on attempt {attempt}; retrying once"
                    )
                    continue
                if last_timeout is not None:
                    raise ActionError(
                        "vpn_connect_timeout",
                        f"Failed while preparing OpenVPN dependencies ({label})",
                    ) from last_timeout
                raise ActionError(
                    "vpn_connect_timeout",
                    f"Failed while preparing OpenVPN dependencies ({label})",
                )

    def determine_baseline_ip(self) -> None:
        if self.retry_http_get(
            "Baseline exit IP probe",
            self.baseline_file,
            self.verify_url,
            request_timeout=10.0,
        ):
            try:
                payload = json.loads(self.baseline_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            self.baseline_ip = str(payload.get("ip") or "").strip()
        if self.baseline_ip:
            print(f"::notice::Baseline exit IP: {self.baseline_ip}")
        else:
            print("::warning::Could not determine baseline exit IP before connecting")
        write_output("baseline-ip", self.baseline_ip)

    def fetch_token_auth(self) -> tuple[str, str]:
        token = os.environ.get("NORDVPN_TOKEN", "").strip()
        if not token:
            raise ActionError(
                "vpn_auth_failure",
                "NORDVPN_TOKEN is required to derive replacement OpenVPN credentials",
            )
        self.token_auth_file.write_text(
            f"machine api.nordvpn.com\nlogin token\npassword {token}\n",
            encoding="utf-8",
        )
        self.token_auth_file.chmod(0o600)
        try:
            fetched = self.retry_http_get(
                "NordVPN credentials request",
                self.creds_file,
                "https://api.nordvpn.com/v1/users/services/credentials",
                "--netrc-file",
                str(self.token_auth_file),
                non_retryable_http_codes=frozenset({"401", "403"}),
            )
        finally:
            with suppress(FileNotFoundError):
                self.token_auth_file.unlink()
        if not fetched:
            raise ActionError(
                "vpn_auth_failure",
                "Failed to fetch NordVPN OpenVPN credentials",
            )
        try:
            payload = json.loads(self.creds_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ActionError(
                "vpn_auth_failure",
                "Failed to decode NordVPN OpenVPN credentials",
            ) from exc
        user = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "").strip()
        return user, password

    def write_auth_file(self, user: str, password: str, *, source: str) -> None:
        if not user or not password:
            raise ActionError("vpn_auth_failure", "Failed to derive NordVPN credentials")

        print(f"::add-mask::{user}")
        print(f"::add-mask::{password}")
        self.auth_file.write_text(f"{user}\n{password}\n", encoding="utf-8")
        self.auth_file.chmod(0o600)
        self.auth_source = source

    def prepare_auth(self, *, require_token: bool = False) -> None:
        openvpn_user = os.environ.get("OPENVPN_USER", "").strip()
        openvpn_password = os.environ.get("OPENVPN_PASSWORD", "").strip()
        token = os.environ.get("NORDVPN_TOKEN", "").strip()

        if require_token:
            user, password = self.fetch_token_auth()
            print("::notice::Using token-derived OpenVPN tunnel credentials")
            self.write_auth_file(user, password, source="token")
            return

        if openvpn_user or openvpn_password:
            if not openvpn_user or not openvpn_password:
                raise ActionError(
                    "vpn_auth_failure",
                    "Both OPENVPN_USER and OPENVPN_PASSWORD secrets are required",
                )
            user = openvpn_user
            password = openvpn_password
            print("::notice::Using configured OpenVPN tunnel credentials")
            self.write_auth_file(user, password, source="configured")
        elif token:
            user, password = self.fetch_token_auth()
            print("::notice::Using token-derived OpenVPN tunnel credentials")
            self.write_auth_file(user, password, source="token")
        else:
            raise ActionError(
                "vpn_auth_failure",
                "Provide OPENVPN_USER and OPENVPN_PASSWORD secrets or NORDVPN_TOKEN",
            )

    def switch_to_token_auth_after_rejection(self) -> bool:
        token = os.environ.get("NORDVPN_TOKEN", "").strip()
        if self.auth_source != "configured" or not token or self.auth_validated:
            return False
        print(
            "::warning::Configured OpenVPN credentials were rejected; "
            "retrying with token-derived service credentials"
        )
        self.cleanup_openvpn()
        for path in (self.log_file, self.pid_file):
            with suppress(FileNotFoundError):
                path.unlink()
        self.prepare_auth(require_token=True)
        return True

    def recommendation_servers(self, technology: str) -> list[str]:
        excluded_servers = {*self.quarantined_servers, *self.failed_servers}
        recommendation_limit = self.server_limit + len(excluded_servers)
        url = (
            "https://api.nordvpn.com/v1/servers/recommendations"
            f"?limit={recommendation_limit}"
            f"&filters[country_id]={self.country_id}"
            f"&filters[servers_technologies][identifier]={technology}"
        )
        if not self.retry_http_get(
            f"NordVPN server recommendations request ({technology})",
            self.servers_file,
            url,
            "--globoff",
        ):
            return []
        try:
            payload = json.loads(self.servers_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        seen: set[str] = set()
        raw_servers: list[str] = []
        for item in payload:
            hostname = str(item.get("hostname") or "").strip()
            if not hostname or hostname in seen:
                continue
            seen.add(hostname)
            raw_servers.append(hostname)

        filtered = [server for server in raw_servers if server not in excluded_servers]
        if not filtered:
            print(f"::warning::All recommended NordVPN servers are excluded for {technology}")
            return []

        selection_offset = self.technology_selection_offsets.get(technology, 0)
        start_index = (self.selector_index + selection_offset) % len(filtered)
        return [filtered[(start_index + offset) % len(filtered)] for offset in range(len(filtered))]

    def config_url(self, server: str, technology: str) -> str:
        if technology == "openvpn_udp":
            return f"https://downloads.nordcdn.com/configs/files/ovpn_udp/servers/{server}.udp.ovpn"
        if technology == "openvpn_tcp":
            return f"https://downloads.nordcdn.com/configs/files/ovpn_tcp/servers/{server}.tcp.ovpn"
        raise ActionError(
            "vpn_network_error",
            f"Unsupported NordVPN technology identifier: {technology}",
        )

    @staticmethod
    def nba_probe_content_valid(path: Path) -> bool:
        try:
            size = path.stat().st_size
            if size <= 0 or size > NBA_PROBE_MAX_BYTES:
                return False
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False

        result_sets = payload.get("resultSets", payload.get("resultSet"))
        if isinstance(result_sets, dict):
            result_sets = [result_sets]
        if not isinstance(result_sets, list) or not result_sets:
            return False
        for result_set in result_sets:
            if not isinstance(result_set, dict) or result_set.get("name") != "TeamYears":
                continue
            headers = result_set.get("headers")
            rows = result_set.get("rowSet")
            if (
                not isinstance(headers, list)
                or not all(isinstance(header, str) for header in headers)
                or not set(headers) >= NBA_PROBE_EXPECTED_HEADERS
            ):
                continue
            if not isinstance(rows, list) or not rows:
                continue
            if any(isinstance(row, list) and len(row) == len(headers) for row in rows):
                return True
        return False

    def probe_nba_stats(self, *, attempt_deadline: float | None = None) -> bool:
        if not self.nba_probe_enabled:
            self.nba_probe_status = "disabled"
            self.nba_probe_diagnostic = "NBA Stats probe disabled by configuration"
            print("::notice::NBA Stats API probe is disabled")
            return True

        limits = self.probe_time_limits(self.nba_probe_timeout, attempt_deadline)
        if limits is None:
            self.nba_probe_status = "budget_exhausted"
            self.nba_probe_diagnostic = (
                "NBA Stats probe skipped because the server-attempt budget is exhausted"
            )
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False

        request_limit, process_limit = limits
        timeout_text = self.format_seconds(request_limit)
        connect_timeout_text = self.format_seconds(min(5.0, request_limit))
        with suppress(FileNotFoundError):
            self.nba_probe_file.unlink()

        cmd = [
            "curl",
            "-sS",
            "--compressed",
            "--connect-timeout",
            connect_timeout_text,
            "--max-time",
            timeout_text,
            "--max-filesize",
            str(NBA_PROBE_MAX_BYTES),
            "-o",
            str(self.nba_probe_file),
            "-w",
            "%{http_code}",
        ]
        for name, value in NBA_PROBE_HEADERS:
            cmd.extend(("-H", f"{name}: {value}"))
        cmd.append(self.nba_probe_url)

        try:
            result = run_command(
                cmd,
                timeout=process_limit,
                capture_output=True,
                check=False,
                termination_grace=NBA_PROBE_TERMINATION_GRACE_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self.nba_probe_status = "timeout"
            self.nba_probe_diagnostic = "NBA Stats probe timed out"
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False

        http_code = (result.stdout or "").strip()
        if result.returncode == 28:
            self.nba_probe_status = "timeout"
            self.nba_probe_diagnostic = "NBA Stats probe timed out"
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False
        if result.returncode != 0:
            self.nba_probe_status = "request_failed"
            self.nba_probe_diagnostic = (
                f"NBA Stats probe request failed with curl exit {result.returncode}"
            )
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False
        if re.fullmatch(r"2\d\d", http_code) is None:
            safe_http_code = http_code if re.fullmatch(r"\d{3}", http_code) else "unknown"
            self.nba_probe_status = "http_error"
            self.nba_probe_diagnostic = f"NBA Stats probe returned HTTP {safe_http_code}"
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False
        if not self.nba_probe_content_valid(self.nba_probe_file):
            self.nba_probe_status = "invalid_content"
            self.nba_probe_diagnostic = "NBA Stats probe returned malformed or unexpected content"
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False

        self.nba_probe_status = "passed"
        self.nba_probe_diagnostic = "NBA Stats response matched the expected JSON structure"
        print("::notice::NBA Stats API probe passed")
        return True

    @staticmethod
    def _safe_stack_probe_token(value: object, default: str) -> str:
        token = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or ""))[:80]
        return token or default

    def probe_nba_discovery_stack(self, *, attempt_deadline: float | None = None) -> bool:
        if not self.nba_stack_probe_enabled:
            if not self.nba_probe_enabled:
                self.nba_probe_status = "disabled"
                self.nba_probe_diagnostic = "NBA probes disabled by configuration"
            print("::notice::NBA discovery stack probe is disabled")
            return True

        limits = self.probe_time_limits(self.nba_stack_probe_timeout, attempt_deadline)
        if limits is None:
            self.nba_probe_status = "stack_budget_exhausted"
            self.nba_probe_diagnostic = (
                "NBA discovery stack probe skipped because the server-attempt budget is exhausted"
            )
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False

        request_limit, process_limit = limits
        uv_path = shutil.which("uv")
        if uv_path is None or not self.nba_stack_probe_script.is_file():
            self.nba_probe_status = "stack_unavailable"
            self.nba_probe_diagnostic = "NBA discovery stack probe runtime is unavailable"
            raise ActionError("nba_stack_unavailable", self.nba_probe_diagnostic)

        endpoint_timeout = max(1, min(10, int(max(1.0, (request_limit - 1.0) / 2))))
        cmd = [
            uv_path,
            "run",
            "--project",
            str(self.project_root),
            "--frozen",
            "--quiet",
            "python",
            str(self.nba_stack_probe_script),
            "--request-timeout-seconds",
            str(endpoint_timeout),
            "--season",
            self.nba_stack_probe_season,
        ]
        try:
            result = run_command(
                cmd,
                timeout=process_limit,
                capture_output=True,
                check=False,
                termination_grace=NBA_PROBE_TERMINATION_GRACE_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self.nba_probe_status = "stack_timeout"
            self.nba_probe_diagnostic = "NBA discovery stack probe timed out"
            print(f"::warning::{self.nba_probe_diagnostic}")
            return False

        payload: object = None
        output_lines = (result.stdout or "").splitlines()
        if output_lines:
            try:
                payload = json.loads(output_lines[-1][:4096])
            except json.JSONDecodeError:
                payload = None
        if result.returncode != 0:
            if not isinstance(payload, dict):
                self.nba_probe_status = "stack_runtime_error"
                self.nba_probe_diagnostic = (
                    "NBA discovery stack probe failed without a valid child attestation"
                )
                raise ActionError("nba_stack_runtime_error", self.nba_probe_diagnostic)

            endpoint = self._safe_stack_probe_token(payload.get("endpoint"), "unknown")
            failure_kind = self._safe_stack_probe_token(payload.get("failure_kind"), "unknown")
            error_type = self._safe_stack_probe_token(payload.get("error_type"), "ProbeFailed")
            if (
                payload.get("status") != "failed"
                or endpoint not in NBA_STACK_PROBE_ENDPOINTS
                or failure_kind not in NBA_STACK_PROBE_FAILURE_KINDS
                or error_type not in NBA_STACK_PROBE_ERROR_TYPES
            ):
                self.nba_probe_status = "stack_invalid_attestation"
                self.nba_probe_diagnostic = (
                    "NBA discovery stack probe returned invalid failure attestation"
                )
                raise ActionError("nba_stack_invalid_attestation", self.nba_probe_diagnostic)

            self.nba_probe_diagnostic = (
                f"NBA discovery stack probe failed at {endpoint} ({error_type})"
            )[:NBA_STACK_PROBE_DIAGNOSTIC_MAX_CHARS]
            if failure_kind == "exception" and error_type in NBA_STACK_PROBE_TRANSPORT_ERROR_TYPES:
                self.nba_probe_status = "stack_transport_failed"
                print(f"::warning::{self.nba_probe_diagnostic}")
                return False
            if (
                failure_kind in {"empty", "invalid_values", "missing_columns"}
                or error_type in NBA_STACK_PROBE_CONTRACT_ERROR_TYPES
            ):
                self.nba_probe_status = "stack_contract_error"
                raise ActionError("nba_stack_contract_error", self.nba_probe_diagnostic)

            self.nba_probe_status = "stack_runtime_error"
            raise ActionError("nba_stack_runtime_error", self.nba_probe_diagnostic)

        if not isinstance(payload, dict) or payload.get("status") != "passed":
            self.nba_probe_status = "stack_invalid_attestation"
            self.nba_probe_diagnostic = "NBA discovery stack probe returned invalid attestation"
            raise ActionError("nba_stack_invalid_attestation", self.nba_probe_diagnostic)
        endpoints = payload.get("endpoints")
        if not isinstance(endpoints, dict):
            self.nba_probe_status = "stack_invalid_attestation"
            self.nba_probe_diagnostic = "NBA discovery stack probe returned invalid attestation"
            raise ActionError("nba_stack_invalid_attestation", self.nba_probe_diagnostic)
        row_counts: dict[str, int] = {}
        for endpoint in ("common_all_players", "league_game_log"):
            endpoint_payload = endpoints.get(endpoint)
            rows = endpoint_payload.get("rows") if isinstance(endpoint_payload, dict) else None
            if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
                self.nba_probe_status = "stack_invalid_attestation"
                self.nba_probe_diagnostic = "NBA discovery stack probe returned invalid attestation"
                raise ActionError("nba_stack_invalid_attestation", self.nba_probe_diagnostic)
            row_counts[endpoint] = rows

        self.nba_probe_status = "passed"
        self.nba_probe_diagnostic = (
            "NBA discovery stack passed "
            f"(common_all_players={row_counts['common_all_players']} rows, "
            f"league_game_log={row_counts['league_game_log']} rows)"
        )[:NBA_STACK_PROBE_DIAGNOSTIC_MAX_CHARS]
        print("::notice::NBA discovery stack probe passed")
        return True

    def verify_connection(
        self,
        interface: str,
        *,
        attempt_deadline: float | None = None,
    ) -> bool:
        self.verification_failure = ""
        route_ok = True
        if self.require_full_tunnel:
            route_ok = self.route_uses_interface(
                "default", interface, attempt_deadline=attempt_deadline
            ) or (
                self.route_uses_interface("0.0.0.0/1", interface, attempt_deadline=attempt_deadline)
                and self.route_uses_interface(
                    "128.0.0.0/1", interface, attempt_deadline=attempt_deadline
                )
            )
        if not route_ok:
            self.verification_failure = "route"
            return False
        if not self.retry_http_get(
            "VPN verification probe",
            self.verify_file,
            self.verify_url,
            attempt_deadline=attempt_deadline,
            request_timeout=10.0,
        ):
            self.verification_failure = "exit_ip"
            return False
        try:
            payload = json.loads(self.verify_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.verification_failure = "exit_ip"
            return False
        exit_ip = str(payload.get("ip") or "").strip()
        if not exit_ip:
            self.verification_failure = "exit_ip"
            return False
        if self.baseline_ip and exit_ip == self.baseline_ip:
            self.verification_failure = "exit_ip"
            return False
        if not self.probe_nba_stats(attempt_deadline=attempt_deadline):
            self.verification_failure = "nba_probe"
            return False
        if not self.probe_nba_discovery_stack(attempt_deadline=attempt_deadline):
            self.verification_failure = "nba_probe"
            return False
        self.exit_ip = exit_ip
        return True

    def attempt_server(self, server: str, technology: str) -> bool:
        print(f"::notice::Attempting NordVPN server {server} over {technology}")
        self.append_unique(self.attempted_servers, server)
        self.last_attempt_auth_failed = False
        self.verification_failure = ""
        attempt_deadline = min(time.monotonic() + self.connect_timeout, self.deadline)
        config_path = self.work_dir / f"{server}.ovpn"
        for path in (
            self.pid_file,
            self.verify_file,
            self.nba_probe_file,
            self.log_file,
            config_path,
        ):
            with suppress(FileNotFoundError):
                path.unlink()

        if not self.retry_http_get(
            f"NordVPN OpenVPN config download for {server} ({technology})",
            config_path,
            self.config_url(server, technology),
            attempt_deadline=attempt_deadline,
        ):
            self.append_unique(self.failed_servers, server)
            print(f"::warning::Skipping server {server} because the configuration download failed")
            return False

        try:
            log_handle = self.log_file.open("a", encoding="utf-8")
        except OSError as exc:
            self.append_unique(self.failed_servers, server)
            raise ActionError(
                "vpn_network_error",
                f"Could not open the OpenVPN log file for {server} over {technology}",
            ) from exc

        try:
            self.openvpn_process = subprocess.Popen(
                [
                    "sudo",
                    "openvpn",
                    "--config",
                    str(config_path),
                    "--auth-user-pass",
                    str(self.auth_file),
                    "--auth-nocache",
                    "--writepid",
                    str(self.pid_file),
                    "--log",
                    str(self.log_file),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log_handle,
                start_new_session=True,
                text=True,
            )
        except OSError as exc:
            log_handle.close()
            self.append_unique(self.failed_servers, server)
            raise ActionError(
                "vpn_connect_timeout",
                f"OpenVPN launch failed for {server} over {technology}",
            ) from exc
        finally:
            log_handle.close()

        self.make_workdir_readable()
        auth_failed = False
        nba_probe_failed = False

        while time.monotonic() < attempt_deadline:
            if self.openvpn_process is None:
                break
            if self.auth_failed_in_log():
                auth_failed = True
                self.last_attempt_auth_failed = True
                print(
                    "::warning::NordVPN rejected the OpenVPN credentials "
                    f"for {server} over {technology}; checking another recommended server"
                )
                break
            process_rc = self.openvpn_process.poll()
            if process_rc is not None:
                if self.auth_failed_in_log():
                    auth_failed = True
                    self.last_attempt_auth_failed = True
                    print(
                        "::warning::NordVPN rejected the OpenVPN credentials "
                        f"for {server} over {technology}; checking another recommended server"
                    )
                    break
                self.append_unique(self.failed_servers, server)
                raise ActionError(
                    "vpn_connect_timeout",
                    f"OpenVPN exited early for {server} over {technology} "
                    f"with exit code {process_rc}",
                )

            pid = (
                self.pid_file.read_text(encoding="utf-8", errors="replace").strip()
                if self.pid_file.exists()
                else ""
            )
            if (
                pid
                and self.pid_alive(pid, attempt_deadline=attempt_deadline)
                and self.initialization_complete()
            ):
                self.auth_validated = True
                interface = self.get_interface(attempt_deadline=attempt_deadline)
                if interface and self.verify_connection(
                    interface,
                    attempt_deadline=attempt_deadline,
                ):
                    self.server = server
                    self.interface = interface
                    self.pid = pid
                    self.status = "connected"
                    return True
                if self.verification_failure == "nba_probe":
                    nba_probe_failed = True
                    break

            time.sleep(min(2.0, max(0.0, attempt_deadline - time.monotonic())))

        if auth_failed:
            self.cleanup_openvpn()
            return False

        self.append_unique(self.failed_servers, server)

        if nba_probe_failed:
            print(
                f"::warning::NBA probes rejected {server} over {technology} "
                f"({self.nba_probe_status}: {self.nba_probe_diagnostic}); "
                "quarantining it for this run and trying the next recommended server"
            )
        else:
            print(
                f"::warning::VPN verification failed for {server} over {technology}; "
                "trying the next recommended server"
            )
        self.make_workdir_readable()
        if self.log_file.exists():
            run_quiet(["sudo", "tail", "-20", str(self.log_file)], timeout=10)
        self.cleanup_openvpn()
        return False

    def run(self) -> int:
        self.prepare_workdir()
        self.install_dependencies()
        self.determine_baseline_ip()
        self.prepare_auth(require_token=self.require_token_auth)

        retried_token_credentials = False
        auth_recovery_round = 0
        while True:
            technologies = [self.technology]
            if self.fallback_technology:
                technologies.append(self.fallback_technology)
            if len(technologies) > 1:
                cursor = self.technology_cursor % len(technologies)
                technologies = technologies[cursor:] + technologies[:cursor]

            saw_auth_failure = False
            auth_rejection_count = 0
            attempted_network = False
            stop_auth_sweep = False
            for technology in technologies:
                self.ensure_budget("technology selection")
                servers = self.recommendation_servers(technology)
                if not servers:
                    attempted_network = True
                    continue
                for server in servers:
                    try:
                        if self.attempt_server(server, technology):
                            print(
                                f"::notice::VPN connected — server: {server}, "
                                f"technology: {technology}, interface: {self.interface}, "
                                f"exit IP: {self.exit_ip}"
                            )
                            write_output("server", self.server)
                            write_output("exit-ip", self.exit_ip)
                            write_output("interface", self.interface)
                            write_output("pid", self.pid)
                            return 0
                    except ActionError as exc:
                        attempted_network = True
                        self.status = exc.status
                        self.make_workdir_readable()
                        self.cleanup_openvpn()
                        if exc.status in {"vpn_connect_timeout", "vpn_network_error"} and (
                            self.remaining_budget() > 0
                        ):
                            print(
                                "::warning::"
                                f"{exc.message}; trying the next recommended server "
                                "if budget remains"
                            )
                            continue
                        raise
                    attempted_network = True
                    if self.last_attempt_auth_failed:
                        saw_auth_failure = True
                        auth_rejection_count += 1
                        self.technology_selection_offsets[technology] = (
                            self.technology_selection_offsets.get(technology, 0) + 1
                        )
                        if auth_rejection_count >= self.auth_rejection_limit:
                            print(
                                "::warning::Reached the bounded authentication-rejection "
                                f"limit ({self.auth_rejection_limit}); pausing this server sweep"
                            )
                            stop_auth_sweep = True
                            break
                if stop_auth_sweep:
                    break

            if self.remaining_budget() <= 0:
                raise ActionError(
                    "vpn_connect_timeout",
                    "VPN tunnel timed out before a verified connection was established",
                )
            if saw_auth_failure and not retried_token_credentials:
                retried_token_credentials = True
                if self.switch_to_token_auth_after_rejection():
                    continue

            if saw_auth_failure and auth_recovery_round < self.auth_recovery_rounds:
                auth_recovery_round += 1
                self.technology_cursor += 1
                delay = (
                    self.auth_recovery_base_delay * auth_recovery_round + self.selector_index % 3
                )
                if self.sleep_with_budget(
                    f"Authentication recovery round {auth_recovery_round}/"
                    f"{self.auth_recovery_rounds}",
                    delay,
                    minimum_after=float(self.connect_timeout),
                ):
                    continue

            self.make_workdir_readable()
            if self.log_file.exists():
                run_quiet(["sudo", "tail", "-50", str(self.log_file)], timeout=10)

            if saw_auth_failure:
                raise ActionError(
                    "vpn_auth_failure",
                    "NordVPN rejected the active OpenVPN credentials after bounded "
                    "server and capacity recovery",
                )
            if not attempted_network:
                raise ActionError(
                    "vpn_network_error",
                    "VPN tunnel failed before any server attempt could be made",
                )
            raise ActionError(
                "vpn_network_error",
                "VPN tunnel failed to establish with the recommended servers",
            )

    def finalize(self) -> None:
        self.cleanup_sensitive()
        write_output("status", self.status)
        write_output("auth-source", self.auth_source if self.status == "connected" else "")
        write_output("nba-probe-status", self.nba_probe_status)
        write_output("nba-probe-diagnostic", self.nba_probe_diagnostic)
        write_output("attempted-servers-json", json.dumps(self.attempted_servers))
        write_output("failed-servers-json", json.dumps(self.failed_servers))


def main() -> int:
    action: NordVpnConnectAction | None = None
    try:
        action = NordVpnConnectAction()
        return action.run()
    except ActionError as exc:
        if action is None:
            write_output("status", exc.status)
            write_output("auth-source", "")
            write_output("nba-probe-status", "not_run")
            write_output("nba-probe-diagnostic", "NBA Stats probe did not run")
            write_output("attempted-servers-json", "[]")
            write_output("failed-servers-json", "[]")
            print(f"::error::{exc.message}")
            return 1
        action.status = exc.status
        print(f"::error::{exc.message}")
        action.make_workdir_readable()
        action.cleanup_openvpn()
        return 1
    except Exception as exc:
        message = f"NordVPN action crashed unexpectedly: {exc}"
        if action is None:
            write_output("status", "vpn_network_error")
            write_output("auth-source", "")
            write_output("nba-probe-status", "not_run")
            write_output("nba-probe-diagnostic", "NBA Stats probe did not run")
            write_output("attempted-servers-json", "[]")
            write_output("failed-servers-json", "[]")
            print(f"::error::{message}")
            return 1
        action.status = "vpn_network_error"
        print(f"::error::{message}")
        action.make_workdir_readable()
        action.cleanup_openvpn()
        return 1
    finally:
        if action is not None:
            action.finalize()


if __name__ == "__main__":
    raise SystemExit(main())
