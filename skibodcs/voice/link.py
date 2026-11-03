"""Link to the DCS Export module: UDP telemetry in, TCP cockpit commands out.
Both sides tolerate DCS not running: the app just keeps retrying quietly."""
from __future__ import annotations
import json
import socket
import threading
import time

from .state import World


class DCSLink:
    def __init__(self, world: World, telemetry_port: int = 14501, command_port: int = 14500,
                 host: str = "127.0.0.1"):
        self.world, self.host = world, host
        self.telemetry_port, self.command_port = telemetry_port, command_port
        self._udp: socket.socket | None = None
        self._tcp: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.bound_port = telemetry_port

    # -- telemetry (DCS -> app)
    def start(self):
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.bind((self.host, self.telemetry_port))
        self.bound_port = self._udp.getsockname()[1]
        self._udp.settimeout(0.25)
        self._thread = threading.Thread(target=self._rx, daemon=True)
        self._thread.start()

    def _rx(self):
        while not self._stop.is_set():
            try:
                data, _ = self._udp.recvfrom(65535)
            except (socket.timeout, OSError):
                continue
            try:
                self.world.update_from_payload(json.loads(data), time.time())
            except (ValueError, KeyError, TypeError):
                pass                                   # ignore malformed packets

    def stop(self):
        self._stop.set()
        for s in (self._udp, self._tcp):
            try:
                s and s.close()
            except OSError:
                pass

    @property
    def dcs_alive(self) -> bool:
        return time.time() - self.world.updated < 3.0

    # -- commands (app -> DCS)
    def _connect(self) -> bool:
        try:
            s = socket.create_connection((self.host, self.command_port), timeout=0.5)
            s.settimeout(0.5)
            self._tcp = s
            return True
        except OSError:
            self._tcp = None
            return False

    def send(self, dev: int, cmd: int, val: float, release_delay: float = 0.08) -> bool:
        """Returns False if DCS isn't reachable (caller can say 'unable')."""
        if self._tcp is None and not self._connect():
            return False
        try:
            self._tcp.sendall(f"{dev},{cmd},{val}\n".encode())
            return True
        except OSError:
            self._tcp = None
            return self._connect() and self.send(dev, cmd, val)

    def send_all(self, cmds: list[tuple[int, int, float]], gap: float = 0.08) -> bool:
        ok = True
        for i, (d, c, v) in enumerate(cmds):
            ok &= self.send(d, c, v)
            if i < len(cmds) - 1:
                time.sleep(gap)
        return ok


class HookClient:
    """Wingman/mission commands -> Hook (TCP, JSON lines). Waits for the matching reply so the app
    only announces what the sim confirmed. Never raises: failures come back as ok=False."""
    def __init__(self, host: str = "127.0.0.1", port: int = 14510, timeout: float = 2.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._s: socket.socket | None = None
        self._buf = b""
        self._lock = threading.Lock()

    def _connect(self) -> bool:
        try:
            self._s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._s.settimeout(self.timeout)
            self._buf = b""
            return True
        except OSError:
            self._s = None
            return False

    def request(self, cmd: dict) -> tuple[bool, str]:
        with self._lock:
            for attempt in (1, 2):
                if self._s is None and not self._connect():
                    return False, "DCS hook unreachable"
                try:
                    self._s.sendall((json.dumps(cmd) + "\n").encode())
                    deadline = time.time() + self.timeout
                    while time.time() < deadline:
                        while b"\n" in self._buf:
                            line, self._buf = self._buf.split(b"\n", 1)
                            try:
                                rep = json.loads(line)
                            except ValueError:
                                continue
                            if rep.get("id") == cmd.get("id"):          # ignore stale replies
                                return bool(rep.get("ok")), str(rep.get("detail", ""))
                        chunk = self._s.recv(4096)
                        if not chunk:
                            raise OSError("closed")
                        self._buf += chunk
                    return False, "no reply from DCS"
                except socket.timeout:
                    return False, "no reply from DCS"
                except OSError:
                    self._s = None                                       # reconnect once, then give up
            return False, "DCS hook unreachable"


class HookStatus:
    """UDP listener for Hook heartbeats and mission events (kills, deaths, landings)."""
    def __init__(self, world: World, port: int = 14511, host: str = "127.0.0.1"):
        self.world, self.host, self.port = world, host, port
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self.bound_port = port

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((self.host, self.port)); self._sock.settimeout(0.25)
        self.bound_port = self._sock.getsockname()[1]
        threading.Thread(target=self._rx, daemon=True).start()

    def _rx(self):
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(65535)
                msg = json.loads(data)
            except (socket.timeout, OSError, ValueError):
                continue
            if msg.get("type") == "heartbeat":
                self.world.hook_seen = time.time()
            elif msg.get("type") == "event":
                self.world.events.append(msg)

    def stop(self):
        self._stop.set()
        try:
            self._sock and self._sock.close()
        except OSError:
            pass

    @property
    def hook_alive(self) -> bool:
        return time.time() - self.world.hook_seen < 3.0
