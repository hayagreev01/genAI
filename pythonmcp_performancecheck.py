import asyncio
import aiohttp
import time
from fastmcp import Client
import logging
import os

MCP_SERVER_URL = "http://localhost:8000/mcp"
HEALTH_BASE_URL = "http://localhost:8000/health"  # Adjust as needed
TEST_TOOL = "greet"
CONCURRENT_CLIENTS = 10
REQUESTS_PER_CLIENT = 20
MONITOR_INTERVAL = 30  # seconds

# Setup logging to both console and a log file
log_filename = f"mcp_loadtest_{time.strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_filename),
    ]
)
logger = logging.getLogger()

results = []
health_snapshots = []

async def fetch_health(session, endpoint):
    url = f"{HEALTH_BASE_URL}/{endpoint}"
    try:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data
    except Exception as e:
        logger.error(f"Error fetching health endpoint {endpoint}: {e}")
        return None

async def monitor_health():
    async with aiohttp.ClientSession() as session:
        while True:
            mem = await fetch_health(session, "memory")
            tasks = await fetch_health(session, "async_tasks")
            gc_stats = await fetch_health(session, "gc_stats")

            timestamp = time.time()
            health_snapshots.append({
                "time": timestamp,
                "memory": mem,
                "async_tasks": tasks,
                "gc_stats": gc_stats
            })

            logger.info(f"Health Metrics at {time.strftime('%X', time.localtime(timestamp))}: Mem={mem}, Tasks={tasks}, GC={gc_stats}")
            await asyncio.sleep(MONITOR_INTERVAL)

async def load_test_worker(worker_id):
    async with Client(MCP_SERVER_URL) as client:
        await client.initialize()
        for i in range(REQUESTS_PER_CLIENT):
            start = time.time()
            try:
                result = await client.call_tool(TEST_TOOL, {"name": f"User{worker_id}-{i}"})
                latency = time.time() - start
                results.append({"worker": worker_id, "index": i, "latency": latency, "success": True})
                logger.info(f"Worker {worker_id} call {i}: latency={latency:.3f}s result={result}")
            except Exception as e:
                latency = time.time() - start
                results.append({"worker": worker_id, "index": i, "latency": latency, "success": False, "error": str(e)})
                logger.error(f"Worker {worker_id} call {i} failed after {latency:.3f}s: {e}")

async def main():
    monitor_task = asyncio.create_task(monitor_health())
    load_tasks = [asyncio.create_task(load_test_worker(wid)) for wid in range(CONCURRENT_CLIENTS)]

    await asyncio.gather(*load_tasks)

    # Cancel health monitoring after load test completes
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    # Summarize load test results
    total = len(results)
    success = sum(r["success"] for r in results)
    errors = total - success
    avg_latency = sum(r["latency"] for r in results) / total if total else 0
    max_latency = max(r["latency"] for r in results) if total else 0
    min_latency = min(r["latency"] for r in results) if total else 0
    logger.info(f"\nSUMMARY: {total} requests, {success} success, {errors} errors")
    logger.info(f"Avg latency: {avg_latency:.3f}s | Min: {min_latency:.3f}s | Max: {max_latency:.3f}s")

    # Summarize health metrics
    if health_snapshots:
        mem_values = [snap["memory"]["rss_mb"] for snap in health_snapshots if snap["memory"]]
        tasks_values = [snap["async_tasks"]["active_async_tasks"] for snap in health_snapshots if snap["async_tasks"]]
        gc_collected = [snap["gc_stats"]["collected"][0] for snap in health_snapshots if snap["gc_stats"]]  # example from gc count
        logger.info(f"Health Metrics Summary over time:")
        logger.info(f"Memory RSS (MB): avg={sum(mem_values)/len(mem_values):.2f}, max={max(mem_values):.2f}")
        logger.info(f"Active Async Tasks: avg={sum(tasks_values)/len(tasks_values):.2f}, max={max(tasks_values)}")
        logger.info(f"GC Collected Count avg={sum(gc_collected)/len(gc_collected):.2f}")

if __name__ == "__main__":
    asyncio.run(main())
