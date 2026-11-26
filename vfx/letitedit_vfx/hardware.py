"""Hardware tier detection so the same effects run (slower) on weak laptops."""

import json
import os
import re
import subprocess
import sys
from functools import lru_cache

TIERS = {
    # preview_scale: fraction of project resolution for previews; samples: EEVEE TAA samples
    "high": {"preview_scale": 0.5, "preview_samples": 16, "final_samples": 32, "analysis_width": 640},
    "medium": {"preview_scale": 0.4, "preview_samples": 8, "final_samples": 24, "analysis_width": 512},
    "low": {"preview_scale": 0.25, "preview_samples": 4, "final_samples": 16, "analysis_width": 384},
}


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


@lru_cache(maxsize=1)
def detect():
    info = {"gpu": None, "vram_mb": None, "ram_gb": None, "cpu_count": os.cpu_count()}
    if sys.platform == "win32":
        smi = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
        out = ""
        for exe in (smi, "nvidia-smi"):     # MCP hosts may launch us with a minimal PATH
            out = _run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
            if out.strip():
                break
        match = re.search(r"^(.+?),\s*(\d+(?:\.\d+)?)\s*$", out, re.M)
        if match:
            info.update(gpu=match.group(1).strip(), vram_mb=int(float(match.group(2))))
        else:   # no NVIDIA tools (or restricted environment): ask Windows
            out = _run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_VideoController | Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json"])
            try:
                d = json.loads(out or 'null') or {}
                info.update(gpu=d.get("Name"), vram_mb=int((d.get("AdapterRAM") or 0) / 2**20) or None)
            except (ValueError, AttributeError):
                pass
            # Win32_VideoController.AdapterRAM is 32-bit (caps at 4 GB); the driver registry key is not.
            reg = _run(["powershell", "-NoProfile", "-Command",
                        "(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
                        "{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -ErrorAction SilentlyContinue)."
                        "'HardwareInformation.qwMemorySize' | Measure-Object -Maximum | "
                        "Select-Object -ExpandProperty Maximum"])
            try:
                if reg.strip():
                    info["vram_mb"] = max(info.get("vram_mb") or 0, int(float(reg.strip()) / 2**20))
            except ValueError:
                pass
        out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        try:
            info["ram_gb"] = round(int(out.strip()) / 2**30)
        except ValueError:
            pass
    elif sys.platform == "darwin":
        chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        mem = _run(["sysctl", "-n", "hw.memsize"]).strip()
        info.update(gpu=chip or "Apple GPU", ram_gb=round(int(mem) / 2**30) if mem.isdigit() else None)
    info["tier"] = classify(info)
    info["settings"] = TIERS[info["tier"]]
    return info


def classify(info):
    gpu = (info.get("gpu") or "").lower()
    vram = info.get("vram_mb") or 0
    if "apple m" in gpu or ("apple" in gpu and "intel" not in gpu):
        return "high" if (info.get("ram_gb") or 0) >= 16 else "medium"
    if any(k in gpu for k in ("nvidia", "geforce", "rtx", "radeon rx", "quadro")) and vram >= 6000:
        return "high"
    if any(k in gpu for k in ("nvidia", "geforce", "radeon", "arc")) and vram >= 2000:
        return "medium"
    return "low"
