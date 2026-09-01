"""Test PLAY variants against the Sentinel RTSP server."""
import re
import socket
import sys

HOST, PORT = "103.250.160.189", 8554
B = f"rtsp://{HOST}:{PORT}/stream/cam01"


def probe(play_url: str, extra_headers: str = ""):
    s = socket.create_connection((HOST, PORT), timeout=6)
    s.settimeout(6)
    try:
        s.sendall(f"OPTIONS {B} RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: p\r\n\r\n".encode())
        s.recv(4096)
        s.sendall(f"DESCRIBE {B} RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: p\r\nAccept: application/sdp\r\n\r\n".encode())
        d = s.recv(16384)
        s.sendall(f"SETUP {B}/trackID=0 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: p\r\nTransport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n\r\n".encode())
        r = s.recv(8192).decode(errors="replace")
        m = re.search(r"Session: (\S+)", r)
        sess = m.group(1) if m else "0"
        req = (f"PLAY {play_url} RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: p\r\n"
               f"Session: {sess}\r\n{extra_headers}\r\n")
        s.sendall(req.encode())
        resp = s.recv(8192).decode(errors="replace")
        return resp.split("\r\n")[0] if resp else "EMPTY"
    except Exception as exc:
        return f"ERR {exc}"
    finally:
        s.close()


TESTS = [
    (B, ""),
    (B + "/", ""),
    (B, "Range: npt=0.000-"),
    (B, "Range: npt=now-"),
    (B, "Require: www.onvif.org/ver20/backchannel"),
    (B, "Scale: 1.000000"),
]
for url, extra in TESTS:
    label = url.replace("rtsp://103.250.160.189:8554", "")
    print(f"PLAY {label:<28} | {extra[:40]:<40} -> {probe(url, extra)}", flush=True)