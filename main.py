# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Union
import httpx
import asyncio
import random
from urllib.parse import quote

app = FastAPI(title="CoC Batch Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====================== CONFIG ======================
# Yahan apne 5-10 CoC API keys daal dena
API_KEYS = []

COC_BASE = "https://api.clashofclans.com/v1"
# ====================================================

class RequestModel(BaseModel):
    action: str
    tag: Optional[str] = None
    tags: Optional[List[str]] = None

def get_random_key():
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
            return {"tag": clan_tag, "success": False, "error": f"HTTP {resp.status_code}", "data": None}
            
    except Exception as e:
        return {"tag": clan_tag, "success": False, "error": str(e), "data": None}

@app.post("/")
@app.post("/coc-api")
async def coc_proxy(req: RequestModel):
    if req.action != "current_war":
        raise HTTPException(status_code=400, detail="Only action 'current_war' supported")
    
    # Single tag support (backward compatible)
    if req.tag and not req.tags:
        tags = [req.tag]
    elif req.tags:
        tags = req.tags
    else:
        raise HTTPException(status_code=400, detail="Provide 'tag' or 'tags'")
    
    # Max 30 tags per request (safety)
    if len(tags) > 30:
        raise HTTPException(status_code=400, detail="Max 30 tags allowed per request")
    
    async with httpx.AsyncClient() as client:
        tasks = [fetch_one_war(client, tag) for tag in tags]
        results = await asyncio.gather(*tasks)
    
    # Format response
    if len(tags) == 1:
        # Single response (compatible with old code)
        r = results[0]
        if r["success"]:
            return {"success": True, "data": r["data"]}
        else:
            return {"success": False, "error": r["error"]}
    
    # Batch response
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
    return {"status": "ok", "keys_loaded": len(API_KEYS)}
