"""Scanner tests run against real sockets — no mocked connection tables."""

import contextlib
import os
import socket

import psutil
import pytest

from app.models.port_info import ProcessInfo
from app.services.port_scanner import PortScanner, ScanError


@contextlib.contextmanager
def listening_socket(host="127.0.0.1"):
    sock = socket.socket(
        socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM
    )
    try:
        sock.bind((host, 0))
        sock.listen(1)
        yield sock, sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture
def scanner():
    return PortScanner()


def find(entries, port):
    return [e for e in entries if e.port == port]


def test_a_real_listening_socket_is_discovered(scanner):
    with listening_socket() as (_sock, port):
        entries = scanner.scan()

    matches = find(entries, port)
    assert matches, f"port {port} was not reported as listening"

    entry = matches[0]
    assert entry.pid == os.getpid()
    assert entry.protocol == "TCP"
    assert entry.address == "127.0.0.1"
    assert entry.status == "RUNNING"
    assert "python" in entry.process.name.lower()
    assert entry.process.create_time is not None


def test_a_closed_socket_disappears(scanner):
    with listening_socket() as (_sock, port):
        assert find(scanner.scan(), port)
    assert not find(scanner.scan(), port)


def test_wildcard_addresses_are_labelled(scanner):
    with listening_socket(host="0.0.0.0") as (_sock, port):
        entries = find(scanner.scan(), port)
    assert entries
    assert entries[0].address == "ALL"


def test_ipv6_listener_is_reported_as_tcp6(scanner):
    try:
        with listening_socket(host="::1") as (_sock, port):
            entries = find(scanner.scan(), port)
    except OSError:
        pytest.skip("IPv6 loopback unavailable on this machine")
    assert entries
    assert entries[0].protocol == "TCP6"


def test_one_process_owning_several_ports_is_represented_accurately(scanner):
    with listening_socket() as (_s1, port_a), listening_socket() as (_s2, port_b):
        entries = scanner.scan()

    first = find(entries, port_a)[0]
    second = find(entries, port_b)[0]

    assert first.pid == second.pid == os.getpid()
    assert port_b in first.sibling_ports
    assert port_a in second.sibling_ports
    assert first.shares_process
    assert set(first.owned_ports) >= {port_a, port_b}


def test_entries_are_sorted_by_port(scanner):
    ports = [e.port for e in scanner.scan()]
    assert ports == sorted(ports)


def test_only_listening_sockets_are_returned(scanner):
    """An established client connection must not appear as a row."""
    with listening_socket() as (server, port):
        client = socket.create_connection(("127.0.0.1", port))
        conn, _ = server.accept()
        try:
            entries = scanner.scan()
            listeners = find(entries, port)
            assert len(listeners) == 1
            client_port = client.getsockname()[1]
            assert not find(entries, client_port)
        finally:
            conn.close()
            client.close()


def test_own_process_is_not_marked_protected(scanner):
    with listening_socket() as (_sock, port):
        entry = find(scanner.scan(), port)[0]
    assert not entry.protected
    assert entry.can_stop


def test_scan_error_is_raised_when_the_table_cannot_be_read(scanner, monkeypatch):
    def denied(**_kwargs):
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", denied)
    with pytest.raises(ScanError):
        scanner.scan()


def test_sockets_without_a_pid_degrade_gracefully(scanner, monkeypatch):
    """Windows hides the owner of some sockets; the row must still render."""

    class FakeAddr:
        ip = "0.0.0.0"
        port = 65000

    class FakeConn:
        status = psutil.CONN_LISTEN
        laddr = FakeAddr()
        pid = None

    monkeypatch.setattr(psutil, "net_connections", lambda **_k: [FakeConn()])

    entry = scanner.scan()[0]
    assert entry.pid == -1
    assert not entry.has_pid
    assert entry.status == "UNKNOWN"
    assert entry.protected
    assert not entry.can_stop


def test_search_blob_covers_every_searchable_field():
    from app.models.port_info import PortEntry

    entry = PortEntry(
        port=8000,
        protocol="TCP",
        address="127.0.0.1",
        process=ProcessInfo(pid=4242, name="python.exe", create_time=1.0),
        description="FastAPI / Uvicorn",
    )
    blob = entry.search_blob
    for needle in ("8000", "tcp", "127.0.0.1", "4242", "python.exe", "fastapi", "running"):
        assert needle in blob
