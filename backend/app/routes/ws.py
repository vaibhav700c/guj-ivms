"""WebSocket — live alert + analytics push to control room clients."""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.eventbus import event_bus

router = APIRouter(tags=["ws"])


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    await websocket.accept()
    queue = await event_bus.subscribe("alerts:new", "analytics:new")
    try:
        await websocket.send_json({"type": "connected", "message": "Live feed established"})
        while True:
            receive_task = asyncio.create_task(websocket.receive_text())
            queue_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {receive_task, queue_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if receive_task in done:
                try:
                    msg = receive_task.result()
                    if msg == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif msg == "close":
                        break
                except Exception:
                    break
            if queue_task in done:
                data = queue_task.result()
                try:
                    payload = data if isinstance(data, dict) else json.loads(data)
                except Exception:
                    payload = {"type": "raw", "data": str(data)}
                await websocket.send_json({"type": "alert", "payload": payload})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue, "alerts:new", "analytics:new")
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/analytics")
async def ws_analytics(websocket: WebSocket):
    """Live analytics overlay stream — all cameras (plan §13 /ws/analytics)."""
    await websocket.accept()
    queue = await event_bus.subscribe("analytics:new")
    try:
        await websocket.send_json({"type": "connected", "channel": "analytics"})
        while True:
            receive_task = asyncio.create_task(websocket.receive_text())
            queue_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {receive_task, queue_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if receive_task in done:
                try:
                    msg = receive_task.result()
                    if msg == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif msg == "close":
                        break
                except Exception:
                    break
            if queue_task in done:
                data = queue_task.result()
                try:
                    payload = data if isinstance(data, dict) else json.loads(data)
                except Exception:
                    payload = {"type": "raw", "data": str(data)}
                await websocket.send_json({"type": "event", "payload": payload})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue, "analytics:new")
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/analytics/{camera_id}")
async def ws_analytics_camera(websocket: WebSocket, camera_id: int):
    """Live analytics overlay stream for one camera (plan §13 /ws/analytics/{camera_id})."""
    await websocket.accept()
    queue = await event_bus.subscribe("analytics:new")
    try:
        await websocket.send_json({
            "type": "connected", "channel": "analytics", "camera_id": camera_id,
        })
        while True:
            receive_task = asyncio.create_task(websocket.receive_text())
            queue_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {receive_task, queue_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if receive_task in done:
                try:
                    msg = receive_task.result()
                    if msg == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif msg == "close":
                        break
                except Exception:
                    break
            if queue_task in done:
                data = queue_task.result()
                try:
                    payload = data if isinstance(data, dict) else json.loads(data)
                except Exception:
                    payload = {"type": "raw", "data": str(data)}
                # Per-camera filter — only forward events for this camera
                try:
                    if int(payload.get("camera_id", -1)) != camera_id:
                        continue
                except (TypeError, ValueError):
                    continue
                await websocket.send_json({"type": "event", "payload": payload})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue, "analytics:new")
        try:
            await websocket.close()
        except Exception:
            pass
