import logging
import ctypes
import multiprocessing
import subprocess
import sys
import threading
import time
from typing import Optional, Protocol

from config import CONFIG, optimal_threads

logger = logging.getLogger(__name__)


class ModelManagerLike(Protocol):
    """Minimal interface the hardware probes need from a model manager."""

    def vram_used(self) -> int: ...

_cache: dict = {}
_cache_lock = threading.Lock()

_model_manager_ref: Optional["ModelManagerLike"] = None
_model_manager_lock = threading.Lock()

_live_cache: dict = {}
_live_lock = threading.Lock()
_live_sampler: Optional[threading.Thread] = None
_live_sampler_stop = threading.Event()
_LIVE_INTERVAL = 1.5
_VRAM_TTL = 5.0
_vram_used_cache: int = 0
_vram_used_at: float = 0.0


def _ram_total_mb() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:
        pass
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        ms = _MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if sys.platform == "win32" and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return int(ms.ullTotalPhys / (1024 * 1024))
    except Exception:
        pass
    return 0


def _ram_available_mb() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().available / (1024 * 1024))
    except Exception:
        pass
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        ms = _MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if sys.platform == "win32" and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return int(ms.ullAvailPhys / (1024 * 1024))
    except Exception:
        pass
    return 0


def _dxgi_vram_total_mb() -> int:
    """Real dedicated video memory via DXGI. Unlike WMI `AdapterRAM`, which is
    capped at 4095 MB by the 32-bit WDDM report, DXGI `GetDesc` reports the
    actual VRAM size (e.g. 6103 MB on a 6 GB AMD card). Returns 0 on failure."""
    if sys.platform != "win32":
        return 0
    try:
        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

        class _DXGI_ADAPTER_DESC(ctypes.Structure):
            _fields_ = [
                ("Description", ctypes.c_wchar * 128),
                ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", ctypes.c_longlong),
            ]

        def _guid(s: str) -> _GUID:
            h = s.replace("-", "")
            return _GUID(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16),
                         (ctypes.c_ubyte * 8)(*[int(h[i:i+2], 16) for i in range(16, 32, 2)]))

        dxgi = ctypes.WinDLL("dxgi.dll")
        create = dxgi.CreateDXGIFactory1
        create.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        factory = ctypes.c_void_p()
        iid = _guid("770AAE78-F26F-4DBA-A829-253C83D1B387")  # IID_IDXGIFactory1
        if create(ctypes.byref(iid), ctypes.byref(factory)) != 0:
            return 0
        vtbl = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        enum_adapters = ctypes.cast(
            vtbl[7],  # IDXGIFactory::EnumAdapters
            ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
                               ctypes.POINTER(ctypes.c_void_p)),
        )
        adapter = ctypes.c_void_p()
        if enum_adapters(factory, 0, ctypes.byref(adapter)) != 0:
            return 0
        avtbl = ctypes.cast(adapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_desc = ctypes.cast(
            avtbl[8],  # IDXGIAdapter::GetDesc
            ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_DXGI_ADAPTER_DESC)),
        )
        desc = _DXGI_ADAPTER_DESC()
        if get_desc(adapter, ctypes.byref(desc)) != 0:
            return 0
        return int(desc.DedicatedVideoMemory // (1024 * 1024))
    except Exception:
        return 0


def _vram_total_mb() -> int:
    try:
        import torch
        if torch.cuda.is_available():
            return int(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024))
    except Exception:
        pass
    dxgi = _dxgi_vram_total_mb()
    if dxgi > 0:
        return dxgi
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Measure-Object -Property AdapterRAM -Sum).Sum"],
                capture_output=True, text=True, timeout=15,
            )
            val = (out.stdout or "").strip()
            if val.isdigit():
                return int(val) // (1024 * 1024)
        else:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            val = (out.stdout or "").strip()
            if val.isdigit():
                return int(val)
    except Exception:
        pass
    return 0


def _vram_used_mb() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        val = (out.stdout or "").strip()
        if val.isdigit():
            return int(val)
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            return int(torch.cuda.memory_allocated() / (1024 * 1024))
    except Exception:
        pass
    # AMD/Vulkan/CPU backends have no nvidia-smi/torch probe; fall back to the
    # estimate-based figure the HardwareMonitor uses for eviction, so the live
    # dashboard and /v1/hardware report real loaded-model VRAM instead of 0.
    try:
        mm = _model_manager_ref
        if mm is not None:
            est = int(mm.vram_used())
            if est > 0:
                return est
    except Exception:
        pass
    return 0


def register_model_manager(model_manager) -> None:
    """Record the active ModelManager so VRAM probes can fall back to its
    loaded-model estimate on backends (AMD/Vulkan/CPU) with no native probe."""
    global _model_manager_ref
    with _model_manager_lock:
        _model_manager_ref = model_manager  # type: ignore[assignment]


def _vram_used_mb_cached(ttl: float = _VRAM_TTL) -> int:
    """VRAM reading with a short TTL so the live sampler never re-spawns
    nvidia-smi/torch probes on every tick."""
    global _vram_used_cache, _vram_used_at
    now = time.time()
    if now - _vram_used_at > ttl:
        _vram_used_cache = _vram_used_mb()
        _vram_used_at = now
    return _vram_used_cache


def _cpu_name() -> str:
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name)"],
                capture_output=True, text=True, timeout=15,
            )
            names = [n.strip() for n in (out.stdout or "").strip().split('\n') if n.strip()]
            if names:
                return " / ".join(names)
        else:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _cpu_utilization() -> float:
    try:
        import psutil
        return float(psutil.cpu_percent(interval=0.5))
    except Exception:
        pass
    return _cpu_utilization_fallback()


def _cpu_utilization_nb() -> float:
    """Non-blocking CPU utilization. psutil keeps its own baseline across calls,
    so interval=None reports real deltas without sleeping."""
    try:
        import psutil
        return float(psutil.cpu_percent(interval=None))
    except Exception:
        pass
    return _cpu_utilization_fallback()


def _cpu_utilization_fallback() -> float:
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        if line.startswith("cpu "):
            parts = line.strip().split()
            idle = int(parts[4])
            total = sum(map(int, parts[1:]))
            if total > 0:
                return round((1.0 - idle / total) * 100, 1)
    except Exception:
        pass
    return 0.0


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _gpu_backend() -> str:
    if _cuda_available():
        return "cuda"
    try:
        import llama_cpp
        if llama_cpp.llama_supports_gpu_offload():
            return "vulkan"
    except ImportError:
        pass
    except Exception:
        pass
    try:
        import subprocess
        if sys.platform == "win32":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty AdapterRAM)"],
                capture_output=True, text=True, timeout=10,
            )
            for line in (out.stdout or "").strip().split('\n'):
                try:
                    if int(line.strip()) > 0:
                        return "vulkan"
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return "cpu"


def _gpu_name() -> str:
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name)"],
                capture_output=True, text=True, timeout=15,
            )
            names = [n.strip() for n in (out.stdout or "").strip().split('\n') if n.strip()]
            if names:
                return " / ".join(names)
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        names = [n.strip() for n in (out.stdout or "").strip().split('\n') if n.strip()]
        if names:
            return " / ".join(names)
    except Exception:
        pass
    return ""


def live_readings() -> dict:
    """Cheap, non-blocking dynamic readings for the realtime dashboard."""
    return {
        "ram_total_mb": _ram_total_mb(),
        "ram_available_mb": _ram_available_mb(),
        "gpu_vram_used_mb": _vram_used_mb_cached(),
        "cpu_utilization": _cpu_utilization_nb(),
        "detected_at": time.time(),
    }


def _sample_loop():
    while not _live_sampler_stop.is_set():
        try:
            with _live_lock:
                _live_cache.update(live_readings())
        except Exception:
            pass
        _live_sampler_stop.wait(_LIVE_INTERVAL)


def _ensure_live_sampler():
    global _live_sampler
    if _live_sampler is None or not _live_sampler.is_alive():
        _live_sampler_stop.clear()
        _live_sampler = threading.Thread(target=_sample_loop, daemon=True, name="hw-live-sampler")
        _live_sampler.start()


def get_live(force: bool = False) -> dict:
    """Latest dynamic readings; seeds + starts the background sampler on first use."""
    if not _live_cache or force:
        with _live_lock:
            if not _live_cache or force:
                _live_cache.update(live_readings())
                _ensure_live_sampler()
    return dict(_live_cache)


def detect_hardware(force: bool = False) -> dict:
    if _cache and not force:
        static = dict(_cache)
    else:
        with _cache_lock:
            if _cache and not force:
                static = dict(_cache)
            else:
                static = {
                    "cpu_cores": multiprocessing.cpu_count(),
                    "cpu_name": _cpu_name(),
                    "ram_total_mb": _ram_total_mb(),
                    "ram_available_mb": _ram_available_mb(),
                    "gpu_name": _gpu_name(),
                    "gpu_vram_mb": _vram_total_mb(),
                    "gpu_vram_used_mb": _vram_used_mb(),
                    "gpu_backend": _gpu_backend(),
                    "cpu_utilization": _cpu_utilization(),
                    "detected_at": time.time(),
                }
                _cache.update(static)
                static = dict(_cache)
    merged = dict(static)
    merged.update(get_live(force=force))
    return merged


class HardwareMonitor:
    """Background thread that enforces hardware budgets by evicting models
    when VRAM, RAM, or CPU budgets are exceeded."""

    def __init__(self, model_manager, check_interval: float = 30.0):
        self._mm = model_manager
        self._check_interval = check_interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._violations = 0

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hw-monitor")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self):
        while not self._stop.is_set():
            time.sleep(self._check_interval)
            self._enforce()

    def _enforce(self):
        with self._lock:
            info = detect_hardware(force=False)
            ram_avail = info.get("ram_available_mb", 0)
            vram_total = info.get("gpu_vram_mb", 0)
            vram_budget = CONFIG.vram_budget_mb or (vram_total - 1024 if vram_total else 0)
            vram_used = info.get("gpu_vram_used_mb", 0)
            cpu_util = info.get("cpu_utilization", 0.0)

            if ram_avail > 0 and ram_avail < 4096:
                logger.warning(f"RAM low: {ram_avail} MB available (floor 4096 MB)")
                self._violations += 1
                self._evict_lru(keep=set())

            if vram_budget > 0 and vram_used > 0 and vram_used > vram_budget:
                logger.warning(f"VRAM over budget: {vram_used} MB used > {vram_budget} MB budget")
                self._violations += 1
                keep = set()
                if CONFIG.auto_load:
                    for n in list(self._mm.instances.keys()):
                        if n == "hy-mt2":
                            keep.add(n)
                self._evict_lru(keep=keep)
            else:
                mm_vram = self._mm.vram_used() if self._mm else 0
                if vram_budget > 0 and mm_vram > 0 and mm_vram > vram_budget:
                    logger.warning(f"VRAM (estimate) over budget: {mm_vram} MB used > {vram_budget} MB budget")
                    self._violations += 1
                    keep = {"hy-mt2"} if CONFIG.auto_load else set()
                    self._evict_lru(keep=keep)

            if cpu_util > 75.0:
                logger.warning(f"CPU high: {cpu_util:.1f}% (cap 75%)")
                self._violations += 1
                target_threads = max(1, (info.get("cpu_cores", 4) + 1) // 3)
                if CONFIG.threads > target_threads:
                    CONFIG.threads = target_threads
                    CONFIG.sync_threads()
                    logger.info(f"Throttled threads to {CONFIG.threads}")
            else:
                # Recover: restore the auto-tuned thread count once CPU pressure
                # subsides so inference speed isn't permanently degraded.
                if CONFIG.threads < optimal_threads():
                    CONFIG.threads = optimal_threads()
                    CONFIG.sync_threads()
                    logger.info(f"Restored threads to {CONFIG.threads} after CPU recovered")

    def _evict_lru(self, keep: set):
        from models import _least_recently_used
        guard = 0
        while guard < 8:
            victim = _least_recently_used(except_names=keep)
            if victim is None:
                break
            try:
                if self._mm.try_unload(victim, timeout=2.0):
                    logger.info(f"HW monitor evicted {victim}")
                else:
                    keep.add(victim)
            except Exception:
                break
            guard += 1


_hw_monitor: Optional[HardwareMonitor] = None
_hw_lock = threading.Lock()


def get_hw_monitor(model_manager=None) -> Optional[HardwareMonitor]:
    """Return the shared HardwareMonitor, (re)binding it to `model_manager`.

    The first call creates and starts the daemon. Later calls with a *different*
    manager swap the bound manager so CLI/arc/test managers are watched instead
    of caching the first (possibly dead) one forever.
    """
    global _hw_monitor
    if model_manager is not None:
        register_model_manager(model_manager)
    if _hw_monitor is not None and model_manager is not None:
        if getattr(_hw_monitor, "_mm", None) is model_manager:
            return _hw_monitor
        with _hw_lock:
            if getattr(_hw_monitor, "_mm", None) is not model_manager:
                old = _hw_monitor
                _hw_monitor = HardwareMonitor(model_manager)
                _hw_monitor.start()
                try:
                    old.stop()
                except Exception:
                    pass
        return _hw_monitor
    if _hw_monitor is None and model_manager is not None:
        with _hw_lock:
            if _hw_monitor is None:
                _hw_monitor = HardwareMonitor(model_manager)
                _hw_monitor.start()
    return _hw_monitor


def auto_tune(force: bool = False) -> dict:
    info = detect_hardware(force=force)
    if CONFIG.threads <= 1:
        CONFIG.threads = optimal_threads()
    if info.get("gpu_vram_mb") and CONFIG.vram_budget_mb == 0:
        CONFIG.vram_budget_mb = max(512, info["gpu_vram_mb"] - 1024)
    ram = info.get("ram_total_mb") or 0
    for m in CONFIG.models:
        if ram and ram < 16384:
            m.n_ctx = min(m.n_ctx, 2048)
        elif ram and ram >= 32768:
            m.n_ctx = max(m.n_ctx, 8192)
    CONFIG.sync_threads()
    logger.info(
        f"Auto-tune: threads={CONFIG.threads}, ram={ram}MB, vram={info.get('gpu_vram_mb', 0)}MB, "
        f"vram_budget={CONFIG.vram_budget_mb}MB"
    )
    return info
