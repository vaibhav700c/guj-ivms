"""Simulator control routes (demo only)."""
from fastapi import APIRouter, Depends, HTTPException

from app.simulator import simulator

router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.get("/status")
def status(_: object = Depends(None)):
    return simulator.status()


@router.post("/start")
async def start(_: object = Depends(None)):
    await simulator.start()
    return simulator.status()


@router.post("/stop")
async def stop(_: object = Depends(None)):
    await simulator.stop()
    return simulator.status()
