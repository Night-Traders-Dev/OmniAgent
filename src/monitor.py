import asyncio
from src.state import state


async def gpu_monitor():
    while True:
        try:
            cmd = "nvidia-smi --query-gpu=temperature.gpu,memory.used --format=csv,noheader,nounits"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                parts = stdout.decode().strip().split(",")
                state.gpu_telemetry = f"{parts[0].strip()}°C | {parts[1].strip()}MB"
        except (OSError, IndexError):
            pass
        await asyncio.sleep(1)
