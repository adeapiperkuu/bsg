"""Phase 0 performance benchmark harness for the bsg backend.

Logs in as the PM dev account and times the hot-path endpoints behind the
Quality Intelligence dashboard:

    GET  /me
    GET  /projects
    GET  /projects/{project_id}/quality-page   (first call = cold, rest = repeat)
    POST /agent-queries                        (quality_intelligence_agent)

It also measures the "first-load waterfall": /me -> /projects -> /quality-page
run strictly one-after-another (as the frontend does today on a cold load of
/quality), and prints the summed latency. That sum is the number the Phase 1B
frontend de-waterfall work must break.

This script only talks HTTP to an already-running backend -- it does not
import any `app.*` modules and does not touch the database directly, so no
DB/connection-string info is needed or read.

Usage:
    backend/.venv/Scripts/python.exe backend/scripts/bench_perf.py
    backend/.venv/Scripts/python.exe backend/scripts/bench_perf.py --base-url http://127.0.0.1:8000/api/v1 --n 5

Credentials are read from BENCH_PM_EMAIL / BENCH_PM_PASSWORD env vars, falling
back to the documented dev PM account (pm@bsg.dev / role delivery_manager).
No secrets (passwords, cookies, CSRF tokens) are ever printed by this script.

Exit code is non-zero if any HTTP request returns a non-2xx status, or if a
precondition (login, project discovery) fails outright.

See docs/PERF_IMPLEMENTATION_PLAN.md (Phase 0) and docs/perf-baseline.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import httpx

# Line-buffer stdout so, when stdout/stderr are merged (e.g. CI logs), the
# progress prints and a final error on stderr don't interleave out of order.
try:
    sys.stdout.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass

DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1"
DEFAULT_N = 5
DEFAULT_AGENT_N = 3  # agent calls are slow (~19s each); default to fewer samples
DEFAULT_TIMEOUT_S = 30.0
AGENT_TIMEOUT_S = 60.0

# Dev-only fallback credentials (documented in docs/PERF_IMPLEMENTATION_PLAN.md).
# Override via BENCH_PM_EMAIL / BENCH_PM_PASSWORD for any other environment.
DEFAULT_PM_EMAIL = "pm@bsg.dev"
DEFAULT_PM_PASSWORD = "bsg-dev-2026"

AGENT_QUERY_TEXT = "What are the top quality risks on this project?"
AGENT_NAME = "quality_intelligence_agent"


class BenchmarkError(RuntimeError):
    """Hard-stop condition: login failed, no visible projects, etc."""


@dataclass
class Sample:
    label: str
    ms: float
    status: int
    ok: bool


@dataclass
class Series:
    label: str
    samples: list[Sample] = field(default_factory=list)

    def add(self, sample: Sample) -> None:
        self.samples.append(sample)

    @property
    def values_ms(self) -> list[float]:
        return [s.ms for s in self.samples]

    @property
    def n(self) -> int:
        return len(self.samples)

    @property
    def min(self) -> float:
        return min(self.values_ms)

    @property
    def max(self) -> float:
        return max(self.values_ms)

    @property
    def p50(self) -> float:
        return percentile(self.values_ms, 50)

    @property
    def p95(self) -> float:
        return percentile(self.values_ms, 95)


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (matches numpy's default 'linear' method)."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


class BenchClient:
    """Thin wrapper around httpx.Client that times requests and soft-records failures."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=timeout)
        self.csrf_token: str | None = None
        self.failures: list[str] = []

    def close(self) -> None:
        self.client.close()

    def _headers(self, mutating: bool) -> dict[str, str]:
        headers: dict[str, str] = {}
        if mutating and self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token
        return headers

    def timed(
        self,
        label: str,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[Sample, httpx.Response]:
        mutating = method.upper() != "GET"
        request_kwargs: dict[str, Any] = {"headers": self._headers(mutating)}
        if json_body is not None:
            request_kwargs["json"] = json_body
        if timeout is not None:
            request_kwargs["timeout"] = timeout  # only override; None means "use client default", not "no timeout"

        started = perf_counter()
        response = self.client.request(method, path, **request_kwargs)
        elapsed_ms = (perf_counter() - started) * 1000

        ok = 200 <= response.status_code < 300
        sample = Sample(label=label, ms=elapsed_ms, status=response.status_code, ok=ok)
        if not ok:
            snippet = response.text[:300].replace("\n", " ")
            self.failures.append(f"{label}: HTTP {response.status_code} on {method} {path} -> {snippet}")
        return sample, response

    def login(self, email: str, password: str) -> dict[str, Any]:
        started = perf_counter()
        response = self.client.post("/auth/login", json={"email": email, "password": password})
        elapsed_ms = (perf_counter() - started) * 1000
        if response.status_code != 200:
            raise BenchmarkError(
                f"Login failed: HTTP {response.status_code} on POST /auth/login -> {response.text[:300]}"
            )
        body = response.json().get("data", {})
        if "stage" in body:
            raise BenchmarkError(
                f"Login returned an MFA challenge (stage={body.get('stage')!r}) instead of a session. "
                "The bench PM account is expected to skip MFA -- check MFA_REQUIRED_ROLES in .env."
            )
        csrf = self.client.cookies.get("csrf_token")
        if not csrf:
            raise BenchmarkError("Login succeeded but no csrf_token cookie was set by the server.")
        self.csrf_token = csrf
        print(f"Logged in as {email} in {elapsed_ms:.1f} ms (role={body.get('role', '?')!r}).")
        return body


def run_series(client: BenchClient, label: str, method: str, path: str, n: int, **kwargs: Any) -> Series:
    series = Series(label=label)
    for i in range(n):
        sample, _ = client.timed(f"{label} [{i + 1}/{n}]", method, path, **kwargs)
        series.add(sample)
        print(f"  {label} run {i + 1}/{n}: {sample.ms:9.1f} ms (status {sample.status})")
    return series


def fmt_row(series: Series | None, label: str | None = None) -> str:
    name = label if label is not None else (series.label if series is not None else "?")
    if series is None or series.n == 0:
        return f"{name:<38} {'-':>9} {'-':>9} {'-':>9} {'-':>9} {'-':>4}"
    return (
        f"{name:<38} {series.min:9.1f} {series.p50:9.1f} {series.p95:9.1f} {series.max:9.1f} {series.n:4d}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 0 performance benchmark harness for the bsg backend.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BENCH_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="Samples per endpoint for /me, /projects, /quality-page (default 5)")
    parser.add_argument(
        "--agent-n",
        type=int,
        default=DEFAULT_AGENT_N,
        help="Samples for POST /agent-queries (default 3; each call can take ~20s)",
    )
    args = parser.parse_args()

    email = os.environ.get("BENCH_PM_EMAIL", DEFAULT_PM_EMAIL)
    password = os.environ.get("BENCH_PM_PASSWORD", DEFAULT_PM_PASSWORD)

    print(f"bench_perf.py -- base_url={args.base_url} n={args.n} agent_n={args.agent_n}")
    print(f"started_at={datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print()

    client = BenchClient(args.base_url)
    try:
        client.login(email, password)

        # ---- First-load waterfall: /me -> /projects -> /quality-page, strictly sequential ----
        print("\n== First-load waterfall (sequential, single run) ==")
        wf_me, _ = client.timed("waterfall /me", "GET", "/me")
        if not wf_me.ok:
            raise BenchmarkError(f"/me failed during waterfall: HTTP {wf_me.status}")

        wf_projects, wf_projects_resp = client.timed("waterfall /projects", "GET", "/projects")
        if not wf_projects.ok:
            raise BenchmarkError(f"/projects failed during waterfall: HTTP {wf_projects.status}")
        projects = wf_projects_resp.json().get("data", [])
        if not projects:
            raise BenchmarkError("PM account has no visible projects -- cannot benchmark quality-page/agent-queries.")
        first_project_id = str(projects[0]["id"])

        wf_quality, _ = client.timed("waterfall /quality-page", "GET", f"/projects/{first_project_id}/quality-page")
        if not wf_quality.ok:
            raise BenchmarkError(f"/quality-page failed during waterfall: HTTP {wf_quality.status}")

        waterfall_sum = wf_me.ms + wf_projects.ms + wf_quality.ms
        print(f"  project_id used: {first_project_id}")
        print(f"  /me            {wf_me.ms:9.1f} ms")
        print(f"  /projects      {wf_projects.ms:9.1f} ms")
        print(f"  /quality-page  {wf_quality.ms:9.1f} ms")
        print(f"  {'-' * 28}")
        print(f"  SUM            {waterfall_sum:9.1f} ms   <- sequential first-load number Phase 1B must break")

        # ---- Repeated endpoint timings ----
        print(f"\n== Endpoint timings (n={args.n}, agent n={args.agent_n}) ==")
        me_series = run_series(client, "GET /me", "GET", "/me", args.n)
        projects_series = run_series(client, "GET /projects", "GET", "/projects", args.n)

        # quality-page: first call in THIS loop is cold, remainder are repeats.
        quality_all = run_series(
            client, "GET /quality-page", "GET", f"/projects/{first_project_id}/quality-page", args.n
        )
        quality_cold = Series(label="GET /quality-page (cold, 1st call)")
        quality_cold.add(quality_all.samples[0])
        quality_repeat = Series(label="GET /quality-page (repeat)")
        for s in quality_all.samples[1:]:
            quality_repeat.add(s)

        # ---- Agent query (slow; smaller N; 60s timeout) ----
        print(f"\n== POST /agent-queries (n={args.agent_n}, timeout=60s; each call can take ~20s) ==")
        agent_body = {
            "agent_name": AGENT_NAME,
            "project_id": first_project_id,
            "query_text": AGENT_QUERY_TEXT,
        }
        agent_series = Series(label="POST /agent-queries")
        for i in range(args.agent_n):
            sample, _ = client.timed(
                f"agent-queries [{i + 1}/{args.agent_n}]",
                "POST",
                "/agent-queries",
                json_body=agent_body,
                timeout=AGENT_TIMEOUT_S,
            )
            agent_series.add(sample)
            print(f"  run {i + 1}/{args.agent_n}: {sample.ms:9.1f} ms (status {sample.status})")

        # ---- Summary table ----
        print("\n" + "=" * 92)
        print("SUMMARY (all times in ms)")
        print("=" * 92)
        print(f"{'Endpoint':<38} {'min':>9} {'p50':>9} {'p95':>9} {'max':>9} {'n':>4}")
        print("-" * 92)
        print(fmt_row(me_series))
        print(fmt_row(projects_series))
        print(fmt_row(quality_cold))
        print(fmt_row(quality_repeat))
        print(fmt_row(agent_series))
        print("-" * 92)
        print(f"{'Waterfall SUM (/me + /projects + /quality-page)':<38} {waterfall_sum:9.1f} ms (single sequential run)")
        print("=" * 92)

        if client.failures:
            print("\nFAILURES:")
            for failure in client.failures:
                print(f"  - {failure}")
            print(f"\n{len(client.failures)} request(s) returned a non-2xx status. Exiting non-zero.")
            return 1

        print("\nAll requests returned 2xx.")
        return 0
    except BenchmarkError as exc:
        print(f"\nBENCHMARK ERROR: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"\nHTTP TRANSPORT ERROR: {exc!r}", file=sys.stderr)
        print("Is the backend running at the given --base-url?", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
