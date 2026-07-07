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
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
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
        self.baseline_file = self.work_dir / "baseline-ip.json"
        self.auth_file = self.work_dir / "vpn-auth.txt"

        self.selector_index = env_int("LANE_INDEX", env_int("SHARD_INDEX", 0), minimum=0)
        self.server_limit = env_int("SERVER_LIMIT", 4, minimum=1)
        self.connect_timeout = env_int("CONNECT_TIMEOUT_SECONDS", 90, minimum=30)
        self.overall_timeout = env_int("OVERALL_TIMEOUT_SECONDS", 300, minimum=30)
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
        self.quarantined_servers = parse_quarantined_servers(
            os.environ.get("QUARANTINED_SERVERS_JSON", "[]")
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

    def append_unique(self, values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)

    def make_workdir_readable(self) -> None:
        if not self.work_dir.is_dir():
            return
        run_quiet(["sudo", "chmod", "a+rx", str(self.work_dir)], timeout=10)
        private_paths = {self.auth_file, self.creds_file}
        for path in self.work_dir.iterdir():
            if path in private_paths:
                run_quiet(["sudo", "chmod", "600", str(path)], timeout=10)
            else:
                run_quiet(["sudo", "chmod", "a+rX", str(path)], timeout=10)

    def cleanup_sensitive(self) -> None:
        for path in (
            self.creds_file,
            self.servers_file,
            self.verify_file,
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

    def retry_http_get(self, label: str, output_path: Path, url: str, *extra_args: str) -> bool:
        attempts = 3
        for attempt in range(1, attempts + 1):
            self.ensure_budget(label)
            remaining = self.remaining_budget()
            connect_limit = max(1, min(10, int(remaining)))
            request_limit = max(1, min(30, int(remaining)))
            cmd = [
                "curl",
                "-sS",
                "--connect-timeout",
                str(connect_limit),
                "--max-time",
                str(request_limit),
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
                    timeout=request_limit + 5,
                    capture_output=True,
                    check=False,
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
            if attempt == attempts:
                print(f"::error::{label} failed after {attempt} attempts ({status_text})")
                return False
            sleep_for = attempt * 5
            if self.remaining_budget() <= sleep_for + 5:
                print(
                    f"::error::{label} failed ({status_text}) and retrying would "
                    "exceed the VPN connection budget"
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

    def get_interface(self) -> str:
        try:
            result = run_command(["ip", "-o", "link", "show"], timeout=10)
        except subprocess.TimeoutExpired:
            return ""
        for line in (result.stdout or "").splitlines():
            match = re.search(r": (tun\d+):", line)
            if match:
                return match.group(1)
        return ""

    def route_uses_interface(self, route_expr: str, interface: str) -> bool:
        try:
            result = run_command(["ip", "route", "show", route_expr], timeout=10)
        except subprocess.TimeoutExpired:
            return False
        return f" dev {interface}" in (result.stdout or "")

    def pid_alive(self, pid: str) -> bool:
        try:
            result = run_command(
                ["sudo", "kill", "-0", pid],
                timeout=10,
                capture_output=False,
                check=False,
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
            "--max-time",
            "10",
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
        if not self.retry_http_get(
            "NordVPN credentials request",
            self.creds_file,
            "https://api.nordvpn.com/v1/users/services/credentials",
            "-u",
            f"token:{token}",
        ):
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

    def prepare_auth(self, *, prefer_token: bool = False) -> None:
        openvpn_user = os.environ.get("OPENVPN_USER", "").strip()
        openvpn_password = os.environ.get("OPENVPN_PASSWORD", "").strip()
        token = os.environ.get("NORDVPN_TOKEN", "").strip()

        if prefer_token:
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
        if self.auth_source != "configured" or not token:
            return False
        print(
            "::warning::Configured OpenVPN credentials were rejected; "
            "retrying with token-derived service credentials"
        )
        self.cleanup_openvpn()
        for path in (self.log_file, self.pid_file):
            with suppress(FileNotFoundError):
                path.unlink()
        self.prepare_auth(prefer_token=True)
        return True

    def recommendation_servers(self, technology: str) -> list[str]:
        recommendation_limit = max(
            self.server_limit,
            self.server_limit + len(self.quarantined_servers),
        )
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

        filtered = [server for server in raw_servers if server not in self.quarantined_servers]
        if not filtered:
            print(f"::warning::All recommended NordVPN servers are quarantined for {technology}")
            return []

        start_index = self.selector_index % len(filtered)
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

    def verify_connection(self, interface: str) -> bool:
        route_ok = True
        if self.require_full_tunnel:
            route_ok = self.route_uses_interface("default", interface) or (
                self.route_uses_interface("0.0.0.0/1", interface)
                and self.route_uses_interface("128.0.0.0/1", interface)
            )
        if not route_ok:
            return False
        if not self.retry_http_get(
            "VPN verification probe",
            self.verify_file,
            self.verify_url,
            "--max-time",
            "10",
        ):
            return False
        try:
            payload = json.loads(self.verify_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        exit_ip = str(payload.get("ip") or "").strip()
        if not exit_ip:
            return False
        if self.baseline_ip and exit_ip == self.baseline_ip:
            return False
        self.exit_ip = exit_ip
        return True

    def attempt_server(self, server: str, technology: str) -> bool:
        print(f"::notice::Attempting NordVPN server {server} over {technology}")
        self.append_unique(self.attempted_servers, server)
        config_path = self.work_dir / f"{server}.ovpn"
        for path in (self.pid_file, self.verify_file, self.log_file, config_path):
            with suppress(FileNotFoundError):
                path.unlink()

        if not self.retry_http_get(
            f"NordVPN OpenVPN config download for {server} ({technology})",
            config_path,
            self.config_url(server, technology),
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
        attempt_deadline = min(time.monotonic() + self.connect_timeout, self.deadline)
        auth_failed = False

        while time.monotonic() < attempt_deadline:
            if self.openvpn_process is None:
                break
            if self.auth_failed_in_log():
                auth_failed = True
                print(
                    "::warning::NordVPN rejected the OpenVPN credentials "
                    f"for {server} over {technology}; trying the next recommended server"
                )
                break
            process_rc = self.openvpn_process.poll()
            if process_rc is not None:
                self.append_unique(self.failed_servers, server)
                if self.auth_failed_in_log():
                    auth_failed = True
                    print(
                        "::warning::NordVPN rejected the OpenVPN credentials "
                        f"for {server} over {technology}; trying the next recommended server"
                    )
                    break
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
            if pid and self.pid_alive(pid) and self.initialization_complete():
                interface = self.get_interface()
                if interface and self.verify_connection(interface):
                    self.server = server
                    self.interface = interface
                    self.pid = pid
                    self.status = "connected"
                    return True

            time.sleep(min(2.0, max(0.5, attempt_deadline - time.monotonic())))

        self.append_unique(self.failed_servers, server)
        if auth_failed:
            self.cleanup_openvpn()
            return False

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
        self.prepare_auth()

        retried_token_credentials = False
        while True:
            technologies = [self.technology]
            if self.fallback_technology:
                technologies.append(self.fallback_technology)

            saw_auth_failure = False
            attempted_network = False
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
                        print(
                            "::warning::"
                            f"{exc.message}; trying the next recommended server if budget remains"
                        )
                        self.make_workdir_readable()
                        self.cleanup_openvpn()
                        if exc.status in {"vpn_connect_timeout", "vpn_network_error"} and (
                            self.remaining_budget() > 0
                        ):
                            continue
                        raise
                    attempted_network = True
                    if self.auth_failed_in_log():
                        saw_auth_failure = True

            if self.remaining_budget() <= 0:
                raise ActionError(
                    "vpn_connect_timeout",
                    "VPN tunnel timed out before a verified connection was established",
                )
            if (
                saw_auth_failure
                and not retried_token_credentials
                and self.switch_to_token_auth_after_rejection()
            ):
                retried_token_credentials = True
                continue

            self.make_workdir_readable()
            if self.log_file.exists():
                run_quiet(["sudo", "tail", "-50", str(self.log_file)], timeout=10)

            if saw_auth_failure:
                raise ActionError(
                    "vpn_auth_failure",
                    "NordVPN rejected the OpenVPN credentials on every attempted "
                    "recommended server",
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
