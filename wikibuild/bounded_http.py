"""HTTP reads bounded by an elapsed deadline; the watchdog closes the socket."""

from contextlib import contextmanager
import socket
from threading import Event, Timer


def close_response(response):
    """Interrupt a blocked HTTP read before closing its buffered response."""
    stream = getattr(response, "fp", None)
    sock = getattr(getattr(stream, "raw", None), "_sock", None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    response.close()


@contextmanager
def response_deadline(response, deadline, clock):
    """Read in the caller; the watchdog closes the socket instead of abandoning it."""
    expired = Event()

    def stop():
        expired.set()
        close_response(response)

    timer = Timer(max(0, deadline - clock()), stop)
    timer.daemon = True
    started = False
    try:
        timer.start()
        started = True
        if clock() >= deadline:
            raise TimeoutError("elapsed deadline exhausted")
        yield response
        if expired.is_set() or clock() >= deadline:
            raise TimeoutError("elapsed deadline exhausted")
    finally:
        timer.cancel()
        try:
            close_response(response)
        finally:
            if started:
                timer.join()
