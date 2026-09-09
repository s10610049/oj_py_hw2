"""Opt-in real provider smoke; writes only a local runtime evidence artifact."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Allow one authoring task (at most two billed calls)"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("No model call made. Pass --live to run one real authoring task.")
    async with httpx.AsyncClient(base_url=args.url, timeout=15, trust_env=False) as client:
        login = await client.post(
            "/api/auth/login", json={"username": "admin", "password": "admintestpassword"}
        )
        if login.status_code != 200:
            raise SystemExit("Course-admin login failed; no model call made.")
        config = (await client.get("/api/ai/model-config")).json()["data"]
        if (
            config["provider_url"] != "https://api.deepseek.com"
            or config["model"] != "deepseek-v4-flash"
        ):
            raise SystemExit("Unexpected configured provider/model; no model call made.")
        if not config["api_key_configured"]:
            raise SystemExit("No configured key; no model call made.")
        # Conservative, manually configured peak/cache-miss quote, NOT a provider bill.
        configured = await client.put(
            "/api/ai/model-config",
            json={
                "provider_url": config["provider_url"],
                "model": config["model"],
                "api_key": "",
                "input_price": 0.44,
                "output_price": 1.32,
                "price_unit": 1_000_000,
                "currency": "USD",
            },
        )
        if configured.status_code != 200:
            raise SystemExit("Config update failed; no model call made.")
        requirement = (
            "为Python课程设计一道中等难度题：资源加锁顺序能否形成死锁风险。"
            "抽象为有向图判环，不运行真实线程。明确重复边、自环、不连通图。"
            "本次教学数据n<=100、m<=1000，预期O(n+m)，不声称这组小数据能区分所有复杂度。"
            "最终至少10个完整测试点（小型字面测例加生成器补充测例合计），含每种上述边界、"
            "起点所在分量无环而另一个分量有环、正式测试中的多组输入。"
            "n=100或m=1000的大测例只用test_generator循环构造，不要直接写进JSON字面测例。"
            "提示不得说自环不影响环的存在性。"
            "附可直接stdin/stdout运行的Python标准库"
            "reference_solution和答案核对说明。id使用AI-SMOKE-001。"
        )
        created = await client.post("/api/ai/problem-tasks/", json={"requirement": requirement})
        if created.status_code != 200:
            raise SystemExit(f"Task start failed ({created.status_code})")
        task_id = created.json()["data"]["task_id"]
        previous = None
        for _ in range(125):
            result = await client.get(f"/api/ai/problem-tasks/{task_id}")
            task = result.json()["data"]
            if task["progress"] != previous:
                print(
                    f"{task['elapsed_seconds']:.1f}s {task['status']}: {task['progress']}",
                    flush=True,
                )
                previous = task["progress"]
            if task["status"] in {"completed", "failed", "cancelled"}:
                destination = Path(f"runtime/ai-smoke-{task_id}.json")
                destination.parent.mkdir(exist_ok=True)
                destination.write_text(
                    json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"Evidence: {destination}")
                print(
                    json.dumps(
                        {
                            "status": task["status"],
                            "elapsed_seconds": task["elapsed_seconds"],
                            "usage": task["usage"],
                            "error": task["error"],
                        },
                        ensure_ascii=False,
                    )
                )
                if task["status"] != "completed":
                    raise SystemExit(1)
                return
            await asyncio.sleep(2)
        await client.put(f"/api/ai/problem-tasks/{task_id}/cancel")
        raise SystemExit("Smoke deadline exceeded; cancellation requested")


if __name__ == "__main__":
    asyncio.run(main())
