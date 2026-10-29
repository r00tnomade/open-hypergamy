"""launchd LaunchAgents: one job per schedule, absolute paths, minimal environment (LLD §15.1).

Plists never contain secrets: tokens come from the Keychain at run time (`radar secrets`).
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from opportunity_radar.config import LoadedConfig, ScheduleSettings

LABEL_PREFIX = "com.opportunityradar"
JOB_COMMANDS: dict[str, list[str]] = {
    "sentinel": ["run", "sentinel"],
    "discovery": ["run", "discovery"],
    "digest": ["run", "digest"],
    "backup": ["db", "backup"],
}
Runner = Callable[[list[str]], tuple[int, str]]


def default_agents_dir() -> Path:
    override = os.environ.get("RADAR_LAUNCHD_DIR")
    return Path(override) if override else Path.home() / "Library" / "LaunchAgents"


def _launchctl(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["/bin/launchctl", *args], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def radar_command() -> list[str]:
    """Absolute command prefix for the installed `radar`, never a bare name or a relative path."""
    # Deliberately NOT .resolve(): inside a virtualenv sys.executable is a symlink to the base
    # interpreter, and resolving it would drop the environment (and every dependency) from the job.
    interpreter = Path(os.path.abspath(sys.executable))
    exe = interpreter.parent / "radar"
    if exe.is_file():
        return [str(exe)]
    return [str(interpreter), "-m", "opportunity_radar.cli"]


@dataclass(frozen=True)
class JobSpec:
    job: str
    hour: int
    minute: int
    weekday: int | None  # None = daily

    @property
    def label(self) -> str:
        return f"{LABEL_PREFIX}.{self.job}"


def job_specs(s: ScheduleSettings) -> list[JobSpec]:
    def hm(t: str) -> tuple[int, int]:
        h, _, m = t.partition(":")
        return int(h), int(m)

    return [
        JobSpec("sentinel", *hm(s.sentinel_time), None),
        JobSpec("discovery", *hm(s.discovery_time), s.discovery_weekday),
        JobSpec("digest", *hm(s.digest_time), s.digest_weekday),
        JobSpec("backup", *hm(s.backup_time), None),
    ]


def render_plist(spec: JobSpec, cfg: LoadedConfig, *, config_file: Path | None = None) -> bytes:
    home = cfg.paths.home
    interval: dict[str, int] = {"Hour": spec.hour, "Minute": spec.minute}
    if spec.weekday is not None:
        interval["Weekday"] = spec.weekday
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
        "RADAR_HOME": str(home),
        "RADAR_TRIGGER": "launchd",
    }
    if config_file is not None:
        env["RADAR_CONFIG"] = str(config_file.resolve())
    data = {
        "Label": spec.label,
        "ProgramArguments": [*radar_command(), *JOB_COMMANDS[spec.job]],
        "WorkingDirectory": str(home),
        "EnvironmentVariables": env,
        "StartCalendarInterval": interval,
        "StandardOutPath": str(home / "logs" / f"{spec.job}.out.log"),
        "StandardErrorPath": str(home / "logs" / f"{spec.job}.err.log"),
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
    }
    return plistlib.dumps(data, sort_keys=False)


def installed_jobs(agents_dir: Path | None = None) -> set[str]:
    d = agents_dir or default_agents_dir()
    if not d.is_dir():
        return set()
    return {p.stem.removeprefix(LABEL_PREFIX + ".") for p in d.glob(f"{LABEL_PREFIX}.*.plist")}


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(
    cfg: LoadedConfig,
    *,
    agents_dir: Path | None = None,
    load: bool = True,
    runner: Runner = _launchctl,
    config_file: Path | None = None,
) -> list[tuple[str, Path, str]]:
    """Write one plist per job and (re)load it. Returns (job, path, load result)."""
    d = agents_dir or default_agents_dir()
    d.mkdir(parents=True, exist_ok=True)
    cfg.paths.ensure()
    results = []
    for spec in job_specs(cfg.settings.schedule):
        path = d / f"{spec.label}.plist"
        path.write_bytes(render_plist(spec, cfg, config_file=config_file))
        path.chmod(0o644)
        msg = "written"
        if load:
            runner(["bootout", f"{_domain()}/{spec.label}"])  # ignore: may not be loaded yet
            rc, out = runner(["bootstrap", _domain(), str(path)])
            msg = "loaded" if rc == 0 else f"written, load failed: {out[:120]}"
        results.append((spec.job, path, msg))
    return results


def uninstall(
    *, agents_dir: Path | None = None, runner: Runner = _launchctl, unload: bool = True
) -> list[str]:
    d = agents_dir or default_agents_dir()
    removed = []
    for job in sorted(installed_jobs(d)):
        label = f"{LABEL_PREFIX}.{job}"
        if unload:
            runner(["bootout", f"{_domain()}/{label}"])
        (d / f"{label}.plist").unlink(missing_ok=True)
        removed.append(job)
    return removed
