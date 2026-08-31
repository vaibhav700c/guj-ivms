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
                # client ping/pong keepalive
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
