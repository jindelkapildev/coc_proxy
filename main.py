from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
import asyncio
import random
import os
import json
from urllib.parse import quote

app = FastAPI(title="CoC Batch Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

KEYS_FILE = "keys.json"
COC_BASE = "https://api.clashofclans.com/v1"

def load_keys() -> List[str]:
    """Load keys from local runtime storage or environment fallback"""
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
        except Exception:
            pass
    
    # Fallback to environment variable if keys.json doesn't exist yet
    api_keys_env = os.getenv("COC_API_KEYS", "")
    return [k.strip() for k in api_keys_env.replace("\n", ",").split(",") if k.strip()]

def save_keys(keys: List[str]):
    """Save keys to local file so no redeploy is needed"""
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f)

def get_random_key():
    keys = load_keys()
    if not keys:
        raise HTTPException(status_code=500, detail="No API keys loaded. Please add them via your app's web dashboard.")
    return random.choice(keys)

class RequestModel(BaseModel):
    action: str
    tag: Optional[str] = None
    tags: Optional[List[str]] = None

async def fetch_one_war(client: httpx.AsyncClient, clan_tag: str) -> dict:
    if not clan_tag.startswith("#"):
        clan_tag = "#" + clan_tag
    
    encoded_tag = quote(clan_tag)
    url = f"{COC_BASE}/clans/{encoded_tag}/currentwar"
    
    try:
        headers = {
            "Authorization": f"Bearer {get_random_key()}",
            "Accept": "application/json"
        }
        resp = await client.get(url, headers=headers, timeout=15.0)
        
        if resp.status_code == 200:
            return {"tag": clan_tag, "success": True, "data": resp.json()}
        elif resp.status_code == 404:
            return {"tag": clan_tag, "success": True, "data": {"state": "notInWar"}}
        else:
            return {"tag": clan_tag, "success": False, "error": f"HTTP {resp.status_code}: {resp.text}", "data": None}
            
    except Exception as e:
        return {"tag": clan_tag, "success": False, "error": str(e), "data": None}

@app.post("/")
@app.post("/coc-api")
async def coc_proxy(req: RequestModel):
    if req.action != "current_war":
        raise HTTPException(status_code=400, detail="Only action 'current_war' supported")
    
    if req.tag and not req.tags:
        tags = [req.tag]
    elif req.tags:
        tags = req.tags
    else:
        raise HTTPException(status_code=400, detail="Provide 'tag' or 'tags'")
    
    if len(tags) > 30:
        raise HTTPException(status_code=400, detail="Max 30 tags allowed per request")
    
    async with httpx.AsyncClient() as client:
        tasks = [fetch_one_war(client, tag) for tag in tags]
        results = await asyncio.gather(*tasks)
    
    if len(tags) == 1:
        r = results[0]
        if r["success"]:
            return {"success": True, "data": r["data"]}
        else:
            return {"success": False, "error": r["error"]}
    
    data = {}
    for r in results:
        data[r["tag"]] = r["data"] if r["success"] else None
    
    return {
        "success": True,
        "count": len(tags),
        "data": data
    }

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    outbound_ip = "Unknown"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.ipify.org?format=json", timeout=3.0)
            if resp.status_code == 200:
                outbound_ip = resp.json().get("ip", "Unknown")
    except Exception:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://icanhazip.com", timeout=3.0)
                if resp.status_code == 200:
                    outbound_ip = resp.text.strip()
        except Exception:
            pass

    current_keys = load_keys()
    masked_keys = [k[:10] + "..." + k[-5:] if len(k) > 15 else "***" for k in current_keys]

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CoC Proxy Manager</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px; }}
            .container {{ max-width: 600px; margin: auto; background: #1e293b; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }}
            h1 {{ color: #38bdf8; font-size: 24px; margin-top: 0; }}
            .card {{ background: #0f172a; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #334155; }}
            .ip-box {{ font-size: 22px; font-weight: bold; color: #4ade80; font-family: monospace; }}
            textarea {{ width: 100%; height: 120px; background: #0f172a; color: #f8fafc; border: 1px solid #475569; border-radius: 6px; padding: 10px; font-family: monospace; box-sizing: border-box; }}
            button {{ background: #0284c7; color: white; border: none; padding: 12px 20px; font-size: 16px; border-radius: 6px; cursor: pointer; font-weight: bold; width: 100%; margin-top: 10px; }}
            button:hover {{ background: #0ea5e9; }}
            ul {{ padding-left: 20px; font-family: monospace; font-size: 14px; color: #94a3b8; }}
            .info {{ background: #0369a1; color: #e0f2fe; padding: 12px; border-radius: 6px; font-size: 14px; margin-bottom: 20px; line-height: 1.4; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛡️ CoC Proxy Manager</h1>
            
            <div class="info">
                <strong>No More Redeploy Loops!</strong> Railway changes your IP on redeploy. Use this page to update your API keys safely at runtime without triggering a new build.
            </div>

            <div class="card">
                <h3>🌐 Current Outbound IP</h3>
                <div class="ip-box">{outbound_ip}</div>
                <p style="font-size: 12px; color: #94a3b8; margin: 5px 0 0 0;">Copy this IP and paste it into your Clash of Clans Developer Portal whitelist.</p>
            </div>

            <div class="card">
                <h3>🔑 Add/Update API Keys</h3>
                <form action="/update-keys" method="post">
                    <p style="font-size: 13px; color: #94a3b8; margin-top:0;">Paste your CoC JWT tokens (separated by commas or newlines):</p>
                    <textarea name="keys_text" placeholder="eyJ0eXAiOi..."></textarea>
                    <button type="submit">Save Keys Instantly</button>
                </form>
            </div>

            <div class="card">
                <h3>📊 Active Status ({len(current_keys)} keys loaded)</h3>
                <ul>
                    {"".join([f"<li>{k}</li>" for k in masked_keys]) if masked_keys else "<li>No keys loaded yet. Paste them above!</li>"}
                </ul>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/update-keys", response_class=HTMLResponse)
async def update_keys(keys_text: str = Form(...)):
    new_keys = [k.strip() for k in keys_text.replace("\n", ",").split(",") if k.strip()]
    if new_keys:
        save_keys(new_keys)
    
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Success</title>
        <style>
            body {{ font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding-top: 100px; }}
            .box {{ background: #1e293b; max-width: 400px; margin: auto; padding: 30px; border-radius: 12px; }}
            a {{ color: #38bdf8; text-decoration: none; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="box">
            <h2 style="color: #4ade80;">Keys Saved Successfully!</h2>
            <p>Your API keys have been updated instantly without a redeploy.</p>
            <p><a href="/">← Return to Dashboard</a></p>
        </div>
    </body>
    </html>
    """
