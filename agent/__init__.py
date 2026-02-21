import os
import requests

GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
TOKEN = os.environ["OPENCLAW_GATEWAY_TOKEN"]


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

def spawn_agent(label: str, prompt: str, agent_id: str = "backend-dev", timeout=1800, cleanup="keep") -> dict:
    return openclaw_tool("sessions_spawn", {
        "task": prompt,
        "agentId": agent_id,
        "label": label,
        "runTimeoutSeconds": timeout,
        "cleanup": cleanup
    })
