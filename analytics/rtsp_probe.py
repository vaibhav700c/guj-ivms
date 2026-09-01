"""Minimal RTSP playback probe — verifies SETUP/PLAY + RTP-over-TCP data flow."""
import re
import socket
import sys
import time

HOST, PORT = "103.250.160.189", 8554
BASE = f"rtsp://{HOST}:{PORT}/stream/cam01"
CRLF = "\r\n"


def req(sock, cseq, cmd, url, extra=""):
    body = f"{cmd} {url} RTSP/1.0{CRLF}CSeq: {cseq}{CRLF}User-Agent: probe{CRLF}{extra}{CRLF}"
    sock.sendall(body.encode())
    sock.settimeout(8)
    data = b""
    while True:
        try:
            chunk = sock.recv(8192)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
        if b"\r\n\r\n" in data:
            head, _, rest = data.partition(b"\r\n\r\n")
            clen = 0
            for line in head.decode(errors="replace").split("\r\n"):
                if line.lower().startswith("content-length:"):
                    clen = int(line.split(":", 1)[1].strip())
            if len(rest) >= clen:
                break
    text = data.decode(errors="replace")
    status = text.split(CRLF)[0] if text else "NO RESPONSE"
    print(f"{cseq:>2} {cmd:<9} → {status}")

    # Be careful with DESCRIBE responses that may only partially arrive; a
    # single recv up to 64KB is fine here.
    return data


def main() -> None:
    play_url = sys.argv[1] if len(sys.argv) > 1 else "base"
    s = socket.create_connection((HOST, PORT), timeout=8)

    req(s, 1, "OPTIONS", BASE)
    req(s, 2, "DESCRIBE", BASE, "Accept: application/sdp")
    r = req(s, 3, "SETUP", BASE + "/trackID=0",
            "Transport: RTP/AVP/TCP;unicast;interleaved=0-1")
    m = re.search(rb"Session: (\S+)", r)
    sess = m.group(1).decode() if m else "0"
    print("session:", sess)

    target = BASE if play_url == "base" else BASE + "/"
    req(s, 4, "PLAY", target, f"Session: {sess}")

    print("reading interleaved RTP for 10s…")
    s.settimeout(3)
    t0 = time.time()
    data = b""
    frames = 0
    try:
        while time.time() - t0 < 10:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            data += chunk
            frames += chunk.count(b"\x24")
    except Exception as exc:
        print("err:", exc)
    s.close()
    print(f"bytes: {len(data)} | interleaved packets: {frames} | first: {data[:12].hex()}")


if __name__ == "__main__":
    main()