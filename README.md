# The_Og API 🔑

Seriveri yawe itanga **API keys zawe bwite** (`og-...`). Abakiriya bakoresha *key yawe*,
naho **keys nyazo** (Groq, OpenAI, Claude, ...) ziguma **ihishe** kuri seriveri yawe.

```
Umukiriya ──(og-key)──▶  The_Og API  ──(keys zawe nyazo)──▶  Groq / OpenAI / Claude ...
```

✅ Ikorana na OpenAI SDK (`base_url` yawe) · streaming · amafoto · failover hagati ya providers
✅ Ushobora gukora / guhagarika / gusiba keys kuri `/admin` · imipaka ku munota no ku kwezi · igihe key irangirira
✅ Keys zibikwa nka **hash** (SHA-256): nta wazisoma, ndetse nawe ubwawe

> ℹ️ **Ibi si ukora AI nshya**: ni urugi rwawe (gateway). Amafaranga y'imikoreshereze
> aracyaturuka ku bayitanga (OpenAI, Groq, ...). Mbere yo kugurisha access, soma amategeko (terms)
> ya buri mutanga kugira ngo urebe niba yemera kuyigurisha ku bandi.

## 📁 Dosiye
```
main.py            ← seriveri (FastAPI) + urupapuro rwa /admin
og_core.py         ← ubwenge bw'ingenzi (providers, failover, keys)
requirements.txt   Procfile   .env.example   .gitignore   README.md
```

## 🚀 Gushyira kuri interineti (urugero: Render)
1. **GitHub**: kora repo nshya `The_Og_API`, ushyiremo izo dosiye zose (Add file → Upload files).
2. **Database ihoraho** (ni ngombwa, kugira ngo keys zitazasibama): kora Postgres y'ubuntu kuri
   **Neon** cyangwa **Supabase**, ukoporore *connection string* (`postgresql://...`). Niba Supabase
   idakora, koresha "pooler connection string".
3. **Render** → New → **Web Service** → uhuze repo yawe, hanyuma:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Environment** (reba `.env.example`): `ADMIN_TOKEN`, `DATABASE_URL`, na keys zawe nyazo
     (urugero `GROQ_API_KEY`), `PYTHON_VERSION` = `3.12.3`
4. Tegereza deploy irangire. Uzabona URL nka `https://the-og-api.onrender.com`.
   (Kuri gahunda y'ubuntu seriveri ishobora "gusinzira"; ubusabe bwa mbere bushobora gutinda.)

## 🔑 Gukora key yawe
1. Fungura `https://URL-YAWE/admin`
2. Shyiramo **ADMIN_TOKEN** → **Injira**
3. **Kora key nshya** (izina, imipaka, igihe kirangira) → **IBIKE ako kanya** (ntizongera kugaragara)

Urugero `og-Xa9...` ni yo uha umukiriya.

## 🧪 Kugerageza
```bash
curl https://URL-YAWE/v1/chat/completions \
  -H "Authorization: Bearer og-KEY-YAWE" \
  -H "Content-Type: application/json" \
  -d '{"model":"the-og-ai","messages":[{"role":"user","content":"Muraho!"}]}'
```
Python (OpenAI SDK):
```python
from openai import OpenAI
client = OpenAI(api_key="og-KEY-YAWE", base_url="https://URL-YAWE/v1")
r = client.chat.completions.create(model="the-og-ai",
        messages=[{"role": "user", "content": "Muraho!"}])
print(r.choices[0].message.content)
```
Amafoto: ohereza `image_url` ifite **data URL** (`data:image/jpeg;base64,...`). Streaming: `"stream": true`.

## 🔗 Gukoresha The_Og AI (Streamlit) kuri API yawe
Muri Streamlit **Secrets** ongeraho:
```toml
CUSTOM_API_KEY      = "og-KEY-YAWE"
CUSTOM_BASE_URL     = "https://URL-YAWE/v1"
CUSTOM_MODEL        = "the-og-ai"
CUSTOM_VISION_MODEL = "the-og-ai"
```

## 🔒 Umutekano
- `ADMIN_TOKEN` ibe ndende kandi y'ibanga. Ntuyisangize abakiriya.
- Keys z'abakiriya ntizishyirwe muri code ya browser rusange (zishyirwa kuri seriveri yabo).
- Kora key itandukanye kuri buri mukiriya; urashobora kuyihagarika utagize abandi uhungabanya.
- Imipaka ku munota ibarwa kuri buri seriveri-instance imwe.

## 💻 Kuyikoresha ku mudasobwa yawe
```bash
pip install -r requirements.txt
export ADMIN_TOKEN=igeragezwa123 GROQ_API_KEY=gsk_...
uvicorn main:app --reload      # → http://localhost:8000/admin
```
