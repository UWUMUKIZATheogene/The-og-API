"""
The_Og API  🔑  --  seriveri yawe itanga API keys zawe bwite (og-...)

  • POST /v1/chat/completions   (OpenAI-compatible, ishyigikira streaming + amafoto)
  • GET  /v1/models
  • GET  /admin                 (urupapuro rwo gukora/gucunga keys)
  • /admin/keys ...             (admin API, ikeneye ADMIN_TOKEN)

Keys nyazo z'abatanga serivisi (Groq, OpenAI, Claude, ...) ziba muri ENV y'iseriveri gusa.
"""
import hmac
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import (Boolean, Column, DateTime, Integer, MetaData, String, Table, create_engine,
                        delete, insert, select, update)

import og_core as core

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("og_api")

MODEL_NAME = "the-og-ai"
ADMIN_TOKEN = core.env("ADMIN_TOKEN", "")

# ----------------------------------------------------------------------------
# 🗄️ DATABASE (SQLite ku mudasobwa yawe; Postgres iyo washyizeho DATABASE_URL)
# ----------------------------------------------------------------------------
def _db_url():
    url = core.env("DATABASE_URL", "sqlite:///./og_api.db")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DB_URL = _db_url()
engine = create_engine(
    DB_URL, pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)
meta = MetaData()
api_keys = Table(
    "api_keys", meta,
    Column("id", String(16), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("prefix", String(16), nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True, index=True),
    Column("created_at", DateTime, nullable=False),
    Column("expires_at", DateTime),
    Column("revoked", Boolean, nullable=False, default=False),
    Column("rpm_limit", Integer, nullable=False, default=30),
    Column("monthly_limit", Integer, nullable=False, default=0),  # 0 = nta mupaka
    Column("requests_total", Integer, nullable=False, default=0),
    Column("month", String(7), nullable=False, default=""),
    Column("month_requests", Integer, nullable=False, default=0),
    Column("last_used_at", DateTime),
)
meta.create_all(engine)


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def row_public(r):
    cur_month = now_utc().strftime("%Y-%m")
    status = "active"
    if r["revoked"]:
        status = "revoked"
    elif r["expires_at"] and r["expires_at"] < now_utc():
        status = "expired"
    return {
        "id": r["id"], "name": r["name"], "prefix": r["prefix"] + "…", "status": status,
        "created_at": iso(r["created_at"]), "expires_at": iso(r["expires_at"]),
        "rpm_limit": r["rpm_limit"], "monthly_limit": r["monthly_limit"],
        "requests_total": r["requests_total"],
        "month_requests": r["month_requests"] if r["month"] == cur_month else 0,
        "last_used_at": iso(r["last_used_at"]),
    }


def db_create_key(name, rpm, monthly, days):
    plain, prefix, h = core.new_api_key()
    now = now_utc()
    row = dict(
        id=uuid.uuid4().hex[:12], name=name.strip()[:120], prefix=prefix, key_hash=h, created_at=now,
        expires_at=(now + timedelta(days=days)) if days else None, revoked=False, rpm_limit=rpm,
        monthly_limit=monthly, requests_total=0, month="", month_requests=0, last_used_at=None,
    )
    with engine.begin() as c:
        c.execute(insert(api_keys).values(**row))
    return plain, row


def db_by_hash(h):
    with engine.connect() as c:
        r = c.execute(select(api_keys).where(api_keys.c.key_hash == h)).mappings().first()
        return dict(r) if r else None


def db_list():
    with engine.connect() as c:
        rows = c.execute(select(api_keys).order_by(api_keys.c.created_at.desc())).mappings().all()
        return [dict(r) for r in rows]


def db_set_revoked(key_id, revoked):
    with engine.begin() as c:
        res = c.execute(update(api_keys).where(api_keys.c.id == key_id).values(revoked=revoked))
        return res.rowcount > 0


def db_delete(key_id):
    with engine.begin() as c:
        res = c.execute(delete(api_keys).where(api_keys.c.id == key_id))
        return res.rowcount > 0


def db_count_use(key_id):
    now = now_utc()
    m = now.strftime("%Y-%m")
    with engine.begin() as c:
        c.execute(update(api_keys).where(api_keys.c.id == key_id, api_keys.c.month != m)
                  .values(month=m, month_requests=0))
        c.execute(update(api_keys).where(api_keys.c.id == key_id).values(
            requests_total=api_keys.c.requests_total + 1,
            month_requests=api_keys.c.month_requests + 1, last_used_at=now))


# ----------------------------------------------------------------------------
# 🚦 ERRORS (OpenAI-style, nta provider ivugwa)
# ----------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status, message, code, headers=None):
        self.status, self.message, self.code, self.headers = status, message, code, headers or {}


app = FastAPI(
    title="The_Og API",
    docs_url="/docs" if core.env("ENABLE_DOCS") else None,
    redoc_url=None,
    openapi_url="/openapi.json" if core.env("ENABLE_DOCS") else None,
)
origins = core.as_list(core.env("ALLOWED_ORIGINS", "*")) or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ApiError)
async def _api_error(_, e: ApiError):
    return JSONResponse(
        {"error": {"message": e.message, "type": "invalid_request_error" if e.status < 500 else "server_error",
                   "code": e.code}},
        status_code=e.status, headers=e.headers)


@app.exception_handler(Exception)
async def _unhandled(_, e: Exception):
    log.exception("unhandled error")
    return JSONResponse({"error": {"message": "Internal error.", "type": "server_error", "code": "internal_error"}},
                        status_code=500)


limiter = core.RateLimiter()


def client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


# ----------------------------------------------------------------------------
# 🔐 AUTH
# ----------------------------------------------------------------------------
def authenticate(headers):
    auth = headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else headers.get("x-api-key", "").strip()
    if not token.startswith(core.KEY_PREFIX):
        raise ApiError(401, "Invalid API key.", "invalid_api_key")
    row = db_by_hash(core.hash_key(token))
    if not row or row["revoked"]:
        raise ApiError(401, "Invalid API key.", "invalid_api_key")
    if row["expires_at"] and row["expires_at"] < now_utc():
        raise ApiError(401, "This API key has expired.", "api_key_expired")
    used = row["month_requests"] if row["month"] == now_utc().strftime("%Y-%m") else 0
    if row["monthly_limit"] > 0 and used >= row["monthly_limit"]:
        raise ApiError(429, "Monthly quota exceeded for this API key.", "quota_exceeded")
    if not limiter.allow("k:" + row["id"], row["rpm_limit"]):
        raise ApiError(429, "Rate limit exceeded. Please slow down.", "rate_limit_exceeded", {"Retry-After": "30"})
    return row


def admin_guard(request: Request):
    if not ADMIN_TOKEN:
        raise ApiError(503, "Admin is disabled: set the ADMIN_TOKEN environment variable.", "admin_disabled")
    if not limiter.allow("admin:" + client_ip(request), 40):
        raise ApiError(429, "Too many admin requests.", "rate_limit_exceeded")
    given = request.headers.get("x-admin-token", "")
    if not hmac.compare_digest(given.encode(), ADMIN_TOKEN.encode()):
        raise ApiError(401, "Invalid admin token.", "invalid_admin_token")


# ----------------------------------------------------------------------------
# 🌍 PUBLIC ENDPOINTS
# ----------------------------------------------------------------------------
@app.get("/")
@app.get("/health")
def health():
    return {"name": "The_Og API", "status": "ok"}


@app.get("/v1/models")
def list_models(request: Request):
    authenticate(request.headers)
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "the-og-ai"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    row = await run_in_threadpool(authenticate, request.headers)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except Exception:
        raise ApiError(400, "Request body must be valid JSON.", "invalid_json")
    try:
        messages = core.clean_messages(body.get("messages"))
    except ValueError as e:
        raise ApiError(400, str(e), "invalid_messages")

    try:
        max_tokens = int(body.get("max_tokens") or body.get("max_completion_tokens") or 1024)
    except (TypeError, ValueError):
        max_tokens = 1024
    max_tokens = max(1, min(max_tokens, 4096))
    temperature = body.get("temperature")
    temperature = float(temperature) if isinstance(temperature, (int, float)) else None
    stream = bool(body.get("stream"))

    vision = core.has_image(messages)
    full = core.with_identity(messages)
    gen = core.iter_text(full, vision, max_tokens, temperature)
    try:
        first = await run_in_threadpool(core.prime, gen)
    except core.UpstreamError as e:
        log.warning("all upstreams failed: %s", str(e)[:200])
        raise ApiError(503, "The service is temporarily unavailable. Please try again shortly.", "service_unavailable")

    await run_in_threadpool(db_count_use, row["id"])

    if stream:
        return StreamingResponse(
            core.sse_stream(first, gen, MODEL_NAME), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    text = await run_in_threadpool(lambda: first + "".join(gen))
    return JSONResponse(core.completion_payload(text, MODEL_NAME, core.prompt_text(full)))


# ----------------------------------------------------------------------------
# 🛠️ ADMIN API
# ----------------------------------------------------------------------------
class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rpm_limit: int = Field(default=30, ge=0, le=100000)       # ku munota (0 = nta mupaka)
    monthly_limit: int = Field(default=0, ge=0, le=100000000)  # ku kwezi (0 = nta mupaka)
    expires_days: int = Field(default=0, ge=0, le=3650)        # 0 = ntirangira


@app.post("/admin/keys")
def admin_create(body: KeyCreate, request: Request):
    admin_guard(request)
    plain, row = db_create_key(body.name, body.rpm_limit, body.monthly_limit, body.expires_days)
    return {"key": plain, "note": "Bika iyi key ubu: ntizongera kugaragara.", **row_public(row)}


@app.get("/admin/keys")
def admin_list(request: Request):
    admin_guard(request)
    return {"keys": [row_public(r) for r in db_list()]}


@app.post("/admin/keys/{key_id}/revoke")
def admin_revoke(key_id: str, request: Request):
    admin_guard(request)
    if not db_set_revoked(key_id, True):
        raise ApiError(404, "Key not found.", "not_found")
    return {"ok": True}


@app.post("/admin/keys/{key_id}/enable")
def admin_enable(key_id: str, request: Request):
    admin_guard(request)
    if not db_set_revoked(key_id, False):
        raise ApiError(404, "Key not found.", "not_found")
    return {"ok": True}


@app.delete("/admin/keys/{key_id}")
def admin_delete(key_id: str, request: Request):
    admin_guard(request)
    if not db_delete(key_id):
        raise ApiError(404, "Key not found.", "not_found")
    return {"ok": True}


# ----------------------------------------------------------------------------
# 🖥️ ADMIN PANEL (urupapuro rumwe)
# ----------------------------------------------------------------------------
ADMIN_HTML = """<!DOCTYPE html>
<html lang="rw"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The_Og API · Admin</title>
<style>
:root{--bg:#fff;--card:#f5f7fb;--text:#14181f;--muted:#5d6678;--bd:rgba(20,24,31,.14);--ac:#1e6fe8;--acx:#fff;--bad:#d64545;--ok:#1f9d6b}
@media(prefers-color-scheme:dark){:root{--bg:#0e111b;--card:#171b2c;--text:#ebeef7;--muted:#98a1bc;--bd:rgba(255,255,255,.14);--ac:#3c9bff;--acx:#08111f;--bad:#ff7a7a;--ok:#4fd1a0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 60px}h1{margin:0 0 4px;font-size:1.6rem}p.sub{margin:0 0 20px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:16px;margin-bottom:16px}
label{display:block;font-size:.8rem;color:var(--muted);margin:0 0 4px}
input{width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--bd);background:var(--bg);color:var(--text);font:inherit}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
button{padding:10px 14px;border-radius:10px;border:1px solid var(--bd);background:var(--bg);color:var(--text);font:inherit;cursor:pointer}
button.p{background:var(--ac);color:var(--acx);border-color:var(--ac);font-weight:600}button.d{color:var(--bad)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}.row>div{flex:1;min-width:200px}
table{width:100%;border-collapse:collapse;font-size:.88rem}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--bd);vertical-align:middle}th{color:var(--muted);font-weight:600}
.wrap{overflow-x:auto}.tag{padding:2px 8px;border-radius:99px;font-size:.75rem;border:1px solid var(--bd)}
.active{color:var(--ok)}.revoked,.expired{color:var(--bad)}code{font-family:ui-monospace,Menlo,monospace;word-break:break-all}
#newkey{display:none;border:1px dashed var(--ac)}#msg{min-height:1.3em;color:var(--muted);margin-top:8px}
</style></head><body><main>
<h1>🔑 The_Og API</h1><p class="sub">Kora, genzura kandi uhagarike API keys zawe.</p>

<div class="card"><div class="row"><div><label>🔐 ADMIN TOKEN (iri muri ENV y'iseriveri)</label>
<input id="tok" type="password" placeholder="Shyiramo ADMIN_TOKEN"></div><button class="p" id="login">Injira</button></div><div id="msg"></div></div>

<div class="card" id="newkey"><strong>✅ Key nshya yakozwe — iyibike NONE, ntizongera kugaragara!</strong>
<p><code id="nk"></code></p><button id="copy">📋 Koporora</button></div>

<div class="card" id="createbox" style="display:none"><strong>➕ Kora key nshya</strong>
<div class="grid" style="margin-top:10px">
<div><label>Izina (urugero: Umukiriya A)</label><input id="n_name"></div>
<div><label>Ibisabwa ku munota (0 = nta mupaka)</label><input id="n_rpm" type="number" value="30" min="0"></div>
<div><label>Ibisabwa ku kwezi (0 = nta mupaka)</label><input id="n_mon" type="number" value="0" min="0"></div>
<div><label>Irangira nyuma y'iminsi (0 = ntirangira)</label><input id="n_exp" type="number" value="0" min="0"></div></div>
<p><button class="p" id="create">Kora key</button></p></div>

<div class="card" id="listbox" style="display:none"><strong>📋 Keys zose</strong>
<div class="wrap"><table><thead><tr><th>Izina</th><th>Key</th><th>Status</th><th>Ibisabwa (byose / uku kwezi)</th><th>Imipaka</th><th>Ibikorwa</th></tr></thead><tbody id="rows"></tbody></table></div></div>
</main>
<script>
var T="";var $=function(i){return document.getElementById(i)};
function msg(t){$("msg").textContent=t||""}
function api(path,method,body){return fetch(path,{method:method||"GET",headers:{"Content-Type":"application/json","X-Admin-Token":T},body:body?JSON.stringify(body):undefined}).then(function(r){return r.json().catch(function(){return{}}).then(function(j){if(!r.ok){throw new Error((j.error&&j.error.message)||("Ikosa "+r.status))}return j})})}
function cell(tr,txt,cls){var td=document.createElement("td");if(cls){var s=document.createElement("span");s.className=cls;s.textContent=txt;td.appendChild(s)}else{td.textContent=txt}tr.appendChild(td);return td}
function btn(label,cls,fn){var b=document.createElement("button");b.textContent=label;if(cls)b.className=cls;b.onclick=fn;return b}
function load(){return api("/admin/keys").then(function(d){var tb=$("rows");tb.textContent="";
 if(!d.keys.length){var tr=document.createElement("tr");cell(tr,"Nta key irakorwa.");tb.appendChild(tr)}
 d.keys.forEach(function(k){var tr=document.createElement("tr");cell(tr,k.name);var c=cell(tr,"");var cd=document.createElement("code");cd.textContent=k.prefix;c.appendChild(cd);
  cell(tr,k.status,"tag "+k.status);cell(tr,k.requests_total+" / "+k.month_requests);
  cell(tr,(k.rpm_limit||"∞")+"/min · "+(k.monthly_limit||"∞")+"/ukwezi"+(k.expires_at?" · irangira "+k.expires_at.slice(0,10):""));
  var a=document.createElement("td");
  if(k.status==="revoked"){a.appendChild(btn("▶️ Fungura","",function(){act(k.id,"enable")}))}else{a.appendChild(btn("⏸️ Hagarika","",function(){act(k.id,"revoke")}))}
  a.appendChild(document.createTextNode(" "));a.appendChild(btn("🗑️ Siba","d",function(){if(confirm("Gusiba burundu "+k.name+"?"))del(k.id)}));tr.appendChild(a);tb.appendChild(tr)})})}
function act(id,what){api("/admin/keys/"+id+"/"+what,"POST").then(load).catch(function(e){msg(e.message)})}
function del(id){api("/admin/keys/"+id,"DELETE").then(load).catch(function(e){msg(e.message)})}
$("login").onclick=function(){T=$("tok").value.trim();msg("…");load().then(function(){msg("✅ Winjiye.");$("createbox").style.display="block";$("listbox").style.display="block"}).catch(function(e){msg("❌ "+e.message)})};
$("create").onclick=function(){var name=$("n_name").value.trim();if(!name){msg("Andika izina.");return}
 api("/admin/keys","POST",{name:name,rpm_limit:+$("n_rpm").value||0,monthly_limit:+$("n_mon").value||0,expires_days:+$("n_exp").value||0}).then(function(d){$("nk").textContent=d.key;$("newkey").style.display="block";$("n_name").value="";msg("");load()}).catch(function(e){msg("❌ "+e.message)})};
$("copy").onclick=function(){var t=$("nk").textContent;if(navigator.clipboard){navigator.clipboard.writeText(t).then(function(){$("copy").textContent="✅ Yakoporowe"})}};
</script></body></html>"""


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return HTMLResponse(ADMIN_HTML, headers={"Cache-Control": "no-store"})
