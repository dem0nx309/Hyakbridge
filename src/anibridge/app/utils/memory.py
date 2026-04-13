"""Memory management utilities."""

import ctypes
import ctypes.util
import gc
import sys

__all__ = ["release_memory"]

_libc_name = ctypes.util.find_library("c")
_libc = ctypes.CDLL(_libc_name) if _libc_name else None
_has_malloc_trim = _libc is not None and hasattr(_libc, "malloc_trim")


def release_memory() -> None:
    """Run garbage collection and return freed pages to the OS.

    Calls `gc.collect()` followed by `malloc_trim(0)` on glibc-based systems so that
    the C allocator returns unused pages to the kernel. On non-glibc platforms (e.g.
    musl) only `gc.collect()` runs.

    Setting `PYTHONMALLOC=malloc` is recommended so that the system allocator can
    reclaim memory directly.
    """
    gc.collect()
    if _has_malloc_trim and sys.platform == "linux" and _libc is not None:
        _libc.malloc_trim(0)
