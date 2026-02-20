import os
from dataclasses import dataclass

import requests

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
TOKEN = os.environ["OPENCLAW_GATEWAY_TOKEN"]


@dataclass
class QueueItem:
    item_id: str
    repo: str
    pr_number: int
    title: str
    head_sha: str
    suggested_agent: str | None = None


def openclaw_tool(
    tool: str,
    params: dict,
    session_key: str | None = None,
    channel: str | None = None,
    account_id: str | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    if channel:
        headers["x-openclaw-message-channel"] = channel
    if account_id:
        headers["x-openclaw-account-id"] = account_id

    payload = {
        "tool": tool,
        "action": "json",
        "args": params,
    }
    if session_key:
        payload["sessionKey"] = session_key

    r = requests.post(
        f"{GATEWAY_URL}/tools/invoke", headers=headers, json=payload, timeout=600
    )
    if not r.ok:
        raise RuntimeError(f"Gateway {r.status_code}: {r.text}")
    data = r.json()
    if not data.get("ok", False):
        raise RuntimeError(data)
    return data["result"]

def choose_agent(item: QueueItem) -> str:
    return item.suggested_agent or "backend-dev"

def spawn_fix_agent(pr: dict, task:str, agent_id:str=None, timeout=1800, cleanup="keep") -> dict:
    item = QueueItem(
        item_id=pr["itemId"],
        repo=pr["repo"],
        pr_number=pr["prNumber"],
        title=pr["title"],
        head_sha=pr["headSha"],
        suggested_agent=pr.get("suggestedDevAgent")
    )
    if agent_id is None:
        agent_id = choose_agent(item)
    return openclaw_tool("sessions_spawn", {
        "task": task,
        "agentId": agent_id,
        "label": f"{item.repo}#{item.pr_number}",
        "runTimeoutSeconds": timeout,
        "cleanup": cleanup
    })

def run_dispatch_cycle(items: list[QueueItem]):
    spawned = []

    for item in items:
        try:
            res = spawn_fix_agent(item)
            # only mark dispatched after spawn success
            openclaw_tool("mark_pr_dispatched", {
                "itemId": item.item_id,
                "dispatchType": "fix",
                "headSha": item.head_sha
            })
            spawned.append((item, choose_agent(item), res))
        except Exception as e:
            # log error, continue
            print(f"[WARN] spawn failed for {item.repo}#{item.pr_number}: {e}")

    if spawned:
        nums = ", ".join([f"#{i.pr_number}->{a}" for i, a, _ in spawned])
        msg = f"🔧 Fix agents spawned: {len(spawned)} ({nums})"
        openclaw_tool("message.send", {
            "channel": "telegram",
            "target": "404142725",
            "message": msg
        })

if __name__ == "__main__":
    # Replace with your deterministic queue fetch
    raw = openclaw_tool("get_open_prs", {
        "action": "needs_fix",
        "limit": 10,
        "excludeAlreadyDispatched": True,
        "excludeClaimed": True,
        "includeSuggestedDevAgent": True
    })
    items = [
        QueueItem(
            item_id=r["itemId"],
            repo=r["repo"],
            pr_number=r["prNumber"],
            title=r["title"],
            head_sha=r["headSha"],
            suggested_agent=r.get("suggestedDevAgent")
        )
        for r in raw.get("prs", [])
    ]
    run_dispatch_cycle(items)
