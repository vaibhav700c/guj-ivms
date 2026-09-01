"""Test RTSP playback with PyAV (bundled FFmpeg) — reveals true network behavior."""
import time

import av

url = "rtsp://103.250.160.189:8554/stream/cam01"
print("opening", url, flush=True)
t0 = time.time()
try:
    container = av.open(url, options={
        "rtsp_transport": "tcp",
        "stimeout": "15000000",
    })
    print("container opened:", container.format.name, flush=True)
    for i, frame in enumerate(container.decode(video=0)):
        img = frame.to_ndarray(format="bgr24")
        print("frame", i, img.shape, "after", round(time.time() - t0, 1), "s", flush=True)
        if i == 0:
            av.image.Image.from_ndarray(img, format="bgr24").to_image().save(
                "/tmp/frame_cam01_pyav.jpg")
        if i >= 2:
            break
except Exception as exc:  # noqa: BLE001
    print("ERROR:", type(exc).__name__, str(exc)[:600], flush=True)