"""Host resource probes for memory-aware scheduling on macOS (Apple Silicon).

The scheduler's goal is *sustained* throughput without swapping or Chromium instability, so we
track the signals that actually predict trouble: available memory, swap usage and page-outs."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass


def _run(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


@dataclass
class MemSnapshot:
    total_mb: float
    available_mb: float      # free + inactive + speculative + purgeable (reclaimable without swapping)
    swap_used_mb: float
    pageouts: int            # cumulative since boot; a delta > 0 during a render means memory pressure
    compressed_mb: float


def mem_snapshot() -> MemSnapshot:
    vm = _run(["vm_stat"])
    page = int(re.search(r"page size of (\d+)", vm).group(1)) if "page size of" in vm else 16384

    def pages(key: str) -> int:
        m = re.search(rf"{key}:\s+(\d+)", vm)
        return int(m.group(1)) if m else 0

    avail = (pages("Pages free") + pages("Pages inactive") + pages("Pages speculative") + pages("Pages purgeable")) * page
    compressed = pages("Pages occupied by compressor") * page
    total = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0)
    swap = _run(["sysctl", "-n", "vm.swapusage"])
    m = re.search(r"used = ([\d.]+)M", swap)
    return MemSnapshot(total / 2**20, avail / 2**20, float(m.group(1)) if m else 0.0, pages("Pageouts"),
                       compressed / 2**20)


@dataclass
class HostInfo:
    machine: str
    model: str
    perf_cores: int
    eff_cores: int
    logical_cpus: int
    mem_gb: float


def host_info() -> HostInfo:
    sysctl = lambda k: _run(["sysctl", "-n", k]).strip()
    return HostInfo(
        machine=os.uname().machine,
        model=sysctl("machdep.cpu.brand_string") or sysctl("hw.model"),
        perf_cores=int(sysctl("hw.perflevel0.physicalcpu") or 0),
        eff_cores=int(sysctl("hw.perflevel1.physicalcpu") or 0),
        logical_cpus=os.cpu_count() or 1,
        mem_gb=round(int(sysctl("hw.memsize") or 0) / 2**30, 1),
    )
