
import ctypes
import threading


def find_threads_by_name(name_substring: str):
    return [t for t in threading.enumerate() if name_substring in t.name]


def _async_raise(tid, exctype):
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(tid), ctypes.py_object(exctype)
    )
    if res == 0:
        raise ValueError("invalid thread id")
    elif res > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
        raise SystemError("PyThreadState_SetAsyncExc failed")
