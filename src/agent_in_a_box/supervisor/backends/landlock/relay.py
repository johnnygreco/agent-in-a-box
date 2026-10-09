"""Carry the workload's proxy connections across the network namespace boundary.

The workload's network namespace has only loopback, so it cannot reach the
per-run proxy's TCP port on the host. Two relays connect them through one
Unix socket, the only path out (decisions/0010):

  inside   127.0.0.1:<proxy port> in the sandbox  ->  the mounted Unix socket
  outside  the Unix socket, in a private directory ->  127.0.0.1:<proxy port>

Both are byte pipes. They make no decisions: every request still reaches
the proxy, which decides. If the workload stops the inside relay, it only
loses its own network access.
"""

from __future__ import annotations

import contextlib
import functools
import os
import shutil
import socket
import tempfile
import threading

CHUNK = 65536


def copy_until_closed(source: socket.socket, sink: socket.socket) -> None:
    """Copy bytes one way until the source closes, then pass the close on."""
    with contextlib.suppress(OSError):
        while True:
            data = source.recv(CHUNK)
            if not data:
                break
            sink.sendall(data)
    with contextlib.suppress(OSError):
        sink.shutdown(socket.SHUT_WR)


def pipe(first: socket.socket, second: socket.socket) -> None:
    """Join two connections in both directions; close both when both directions end."""
    one_way = threading.Thread(target=copy_until_closed, args=(first, second), daemon=True)
    one_way.start()
    copy_until_closed(second, first)
    one_way.join()
    first.close()
    second.close()


def connect_unix(path: str) -> socket.socket:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(path)
    return connection


def connect_loopback(port: int) -> socket.socket:
    return socket.create_connection(("127.0.0.1", port))


def serve(listener: socket.socket, connect) -> None:
    """Accept forever; join each accepted connection to a new upstream connection."""
    while True:
        try:
            accepted, _ = listener.accept()
        except OSError:
            return  # the listener was closed
        try:
            upstream = connect()
        except OSError:
            accepted.close()
            continue
        threading.Thread(target=pipe, args=(accepted, upstream), daemon=True).start()


def serve_inside(listener: socket.socket, socket_path: str) -> None:
    """Run inside the sandbox: loopback connections go to the mounted Unix socket."""
    serve(listener, functools.partial(connect_unix, socket_path))


class HostRelay:
    """Run by the supervisor: the Unix socket's connections go to the proxy's TCP port."""

    def __init__(self, proxy_port: int) -> None:
        # A short private directory: Unix socket paths are limited to 108 bytes.
        self.directory = tempfile.mkdtemp(prefix="aib-proxy-")
        self.path = os.path.join(self.directory, "proxy.sock")
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen(64)
        connect = functools.partial(connect_loopback, proxy_port)
        self.thread = threading.Thread(target=serve, args=(self.listener, connect), daemon=True)
        self.thread.start()

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.listener.shutdown(socket.SHUT_RDWR)
        self.listener.close()
        shutil.rmtree(self.directory, ignore_errors=True)
