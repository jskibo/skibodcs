import json, socket, threading, time
from skibodcs.voice.link import DCSLink
from skibodcs.voice.state import World
from skibodcs.voice.audio import radio_fx


def test_telemetry_updates_world():
    w = World(); link = DCSLink(w, telemetry_port=0); link.start()
    payload = {"own": {"model": "F-16C_50", "lat": 41.6, "lon": 41.6, "alt_ft": 5000, "hdg": 90, "gs_kt": 300},
               "objs": [{"id": 7, "lat": 42.0, "lon": 41.6, "alt_ft": 20000, "hdg": 180, "spd_kt": 400, "coal": "red"}]}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(b"garbage", ("127.0.0.1", link.bound_port))            # must be ignored
    s.sendto(json.dumps(payload).encode(), ("127.0.0.1", link.bound_port))
    for _ in range(40):
        if w.contacts: break
        time.sleep(0.05)
    link.stop()
    assert w.own.model == "F-16C_50" and len(w.hostiles()) == 1 and link.dcs_alive


def test_command_send_and_reconnect():
    got = []
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    def serve():
        for _ in range(2):                                          # accept twice: reconnect
            c, _ = srv.accept(); got.append(c.recv(100).decode()); c.close()
    t = threading.Thread(target=serve, daemon=True); t.start()
    link = DCSLink(World(), command_port=port)
    assert link.send(0, 3001, 1.0)
    time.sleep(0.2)
    link._tcp.close() if link._tcp else None; link._tcp = None
    assert link.send(0, 3001, 0.0)
    t.join(2)
    assert got == ["0,3001,1.0\n", "0,3001,0.0\n"]


def test_send_returns_false_when_dcs_down():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    assert DCSLink(World(), command_port=port).send(0, 1, 1.0) is False


def test_radio_fx_returns_valid_wav():
    import io, wave, numpy as np
    sr = 22050; t = np.linspace(0, 0.5, sr // 2, endpoint=False)
    pcm = (np.sin(2 * np.pi * 1000 * t) * 12000).astype(np.int16).tobytes()
    b = io.BytesIO()
    with wave.open(b, "wb") as o: o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr); o.writeframes(pcm)
    out = radio_fx(b.getvalue())
    with wave.open(io.BytesIO(out)) as o: assert o.getframerate() == sr and o.getnframes() == len(t)


def test_theater_loads_airfields_and_bullseye():
    from skibodcs.voice.theater import load_theater
    w = load_theater(World(), "Caucasus", wind_from=310)
    names = {a.name for a in w.airfields}
    assert {"Batumi", "Kutaisi"} <= names and w.bullseye and 40 < w.bullseye[0] < 46
    batumi = next(a for a in w.airfields if a.name == "Batumi")
    assert batumi.runway_headings == [310.0] and abs(batumi.freq_mhz - 131.0) < 0.01
