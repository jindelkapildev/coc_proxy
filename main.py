from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import httpx
import asyncio
import random
import os
from urllib.parse import quote

app = FastAPI(title="CoC Batch Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====================== CONFIG ======================
# Loads API keys from Railway environment variables (comma or newline separated)
API_KEYS_ENV = os.getenv("COC_API_KEYS", "")
API_KEYS = [k.strip() for k in API_KEYS_ENV.replace("\n", ",").split(",") if k.strip()]

COC_BASE = "https://api.clashofclans.com/v1"
# ====================================================

class RequestModel(BaseModel):
    action: str
    tag: Optional[str] = None
    tags: Optional[List[str]] = None

def get_random_key():
    if not API_KEYS:
        raise HTTPException(status_code=500, detail="No API keys loaded. Please configure COC_API_KEYS in Railway variables.")
    return random.choice(API_KEYS)

async def fetch_one_war(client: httpx.AsyncClient, clan_tag: str) -> dict:
    """Single clan current war fetch"""
    if not clan_tag.startswith("#"):
        clan_tag = "#" + clan_tag
    
    encoded_tag = quote(clan_tag)
    url = f"{COC_BASE}/clans/{encoded_tag}/currentwar"
    
    headers = {
        "Authorization": f"Bearer {get_random_key()}",
        "Accept": "application/json"
    }
    
    try:
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

@app.get("/")
async def health():
    """Fetches outbound IP dynamically so you can whitelist it in the CoC Developer Portal"""
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

    return {
        "status": "ok",
        "keys_loaded": len(API_KEYS),
        "outbound_ip": outbound_ip,
        "instructions": "Copy the 'outbound_ip' value above and add it to your Clash of Clans Developer Portal API whitelist."
    }
