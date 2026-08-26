# ============================================================================
# REVENUEAGENTROUTE – V19.1.0 (MONEY PAY & AGENT CORE - RAILWAY OPTIMIERT)
# ============================================================================

import asyncio
import gc
import io
import json
import logging
import os
import uuid
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict

import httpx
import stripe
from fastapi import FastAPI, APIRouter, HTTPException, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from passlib.context import CryptContext
import jwt

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator

# Excel-Import Abhängigkeiten
import pandas as pd
import openpyxl

# ============================================================================
# LOGGING & RATE LIMITER
# ============================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RevenueAgent_MoneyPay")

limiter = Limiter(key_func=get_remote_address)

# ============================================================================
# KONFIGURATION & UMGEBUNGSVARIABLEN
# ============================================================================
from dotenv import load_dotenv
load_dotenv()

GEHEIMER_SCHLUESSEL = os.getenv("SECRET_KEY", "super-geheimer-produktionsschluessel-bitte-aendern")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
STRIPE_GEHEIMER_SCHLUESSEL = os.getenv("STRIPE_SECRET_KEY", "sk_test_...")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_...")

SEPA_IBAN = os.getenv("SEPA_IBAN", "DE89370400440532013000")
SEPA_BIC = os.getenv("SEPA_BIC", "COBADEFFXXX")

stripe.api_key = STRIPE_GEHEIMER_SCHLUESSEL

# Globaler HTTP-Client Pool
global_http_client: Optional[httpx.AsyncClient] = None

# Caches & Speicher
semantic_response_cache: Dict[str, dict] = {}
kunden_speicher: Dict[str, dict] = {}
projekt_speicher: Dict[str, dict] = {}
rechnungs_speicher: Dict[str, dict] = {}
excel_imports: List[Dict] = []
leads: List[Dict] = []
lead_campaigns: List[Dict] = []

current_version: str = "19.1.0"

# ============================================================================
# AUTHENTIFIZIERUNG
# ============================================================================
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/revenue/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

fake_users_db = {
    "admin": {"username": "admin", "password": pwd_context.hash("securepassword"), "role": "admin"},
}

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(days=30)})
    return jwt.encode(to_encode, GEHEIMER_SCHLUESSEL, algorithm="HS256")

# ============================================================================
# SMART AI ROUTER
# ============================================================================
class SmartAIRouter:
    CHEAP_MODEL = "gpt-4o-mini"
    ADVANCED_MODEL = "gpt-4o"
    
    @classmethod
    async def call_llm_efficient(cls, prompt: str, sparte: str) -> str:
        cache_key = hashlib.md5(f"{sparte}:{prompt}".encode()).hexdigest()
        if cache_key in semantic_response_cache:
            return semantic_response_cache[cache_key]["response"]
        
        if not OPENAI_API_KEY or global_http_client is None:
            simulated = f"Simulierte KI-Antwort für '{sparte}'."
            semantic_response_cache[cache_key] = {"response": simulated, "time": datetime.utcnow()}
            return simulated
        
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": cls.CHEAP_MODEL,
            "messages": [{"role": "system", "content": "Präzise B2B-Antworten."}, {"role": "user", "content": prompt}],
            "max_tokens": 400,
            "temperature": 0.2
        }
        
        try:
            res = await global_http_client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            if res.status_code == 200:
                text = res.json()["choices"][0]["message"]["content"]
                semantic_response_cache[cache_key] = {"response": text, "time": datetime.utcnow()}
                return text
            return f"API-Fehler: {res.status_code}"
        except Exception as e:
            return f"Fehler: {str(e)}"

# ============================================================================
# EXCEL-IMPORT ENGINE
# ============================================================================
# ============================================================================
# EXCEL-IMPORT ENGINE
# ============================================================================
# ============================================================================
# EXCEL-IMPORT ENGINE
# ============================================================================
class ExcelImportEngine:
    @staticmethod
    async def process_excel(file: UploadFile) -> Dict:
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(status_code=400, detail="Nur Excel-Dateien (.xlsx, .xls) erlaubt.")

        try:
            contents = await file.read()
            df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
            
            df.columns = [col.strip().lower().replace(' ', '_') for col in df.columns]
            records = df.to_dict(orient='records')
            
            import_record = {
                "filename": file.filename,
                "timestamp": datetime.utcnow().isoformat(),
                "rows": len(records),
                "columns": list(df.columns),
                "data": records
            }
            excel_imports.append(import_record)
            
            # Automatische Lead-Erkennung
            leads_created = 0
            if 'email' in df.columns and 'firma' in df.columns:
                leads_created = len(df)
            
            gc.collect()
            
            return {
                "status": "success",
                "imported_rows": len(records),
                "leads_created": leads_created,
                "columns": list(df.columns),
                "message": f"Excel-Datei '{file.filename}' erfolgreich importiert."
            }
            
        except Exception as e:
            logger.error(f"Excel-Import Fehler: {e}")
            raise HTTPException(status_code=500, detail=f"Fehler beim Verarbeiten der Excel-Datei: {str(e)}")
            
            excel_imports.append({
                "filename": file.filename,
                "timestamp": datetime.utcnow().isoformat(),
                "rows": len(records),
                "columns": list(df.columns)
            })
            
            leads_created = 0
            if 'email' in df.columns and 'firma' in df.columns:
                for _, row in df.iterrows():
                    leads.append({
                        "company": row.get('firma', ''),
                        "email": row.get('email', ''),
                        "source": "Excel-Import",
                        "found_at": datetime.utcnow().isoformat()
                    })
                    leads_created += 1
            
            gc.collect()
            return {
                "status": "success",
                "imported_rows": len(records),
                "leads_created": leads_created,
                "message": f"Excel-Datei '{file.filename}' erfolgreich verarbeitet."
            }
        except Exception as e:
            logger.error(f"Excel-Import Fehler: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# API ROUTER & ENDPOINTS
# ============================================================================
router = APIRouter(prefix="/api/revenue", tags=["RevenueAgent_MoneyPay"])

class RechnungErstellen(BaseModel):
    kunden_email: str = Field(..., pattern=r'^[^@]+@[^@]+\.[^@]+$')
    betrag: float = Field(..., gt=0, le=100000.0)
    beschreibung: str = Field(..., min_length=5, max_length=200)

class PaymentWebhookPayload(BaseModel):
    invoice_id: str
    paid_amount: float

@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = fake_users_db.get(form_data.username)
    if not user or not pwd_context.verify(form_data.password, user["password"]):
        raise HTTPException(status_code=400, detail="Ungültige Anmeldedaten")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}

# WICHTIG: Dieser Endpunkt muss exakt so heißen für den Railway Healthcheck!
@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Money Pay & Agent Core",
        "version": current_version,
        "cache_entries": len(semantic_response_cache)
    }

@router.post("/rechnung/erstellen")
async def rechnung_erstellen(anfrage: RechnungErstellen):
    rechnungs_id = f"inv_{uuid.uuid4().hex[:8]}"
    rechnung = {
        "id": rechnungs_id,
        "kunden_email": anfrage.kunden_email,
        "betrag": anfrage.betrag,
        "beschreibung": anfrage.beschreibung,
        "status": "sent",
        "zahlungs_link": f"https://pay.revenueagentroute.com/{rechnungs_id}"
    }
    rechnungs_speicher[rechnungs_id] = rechnung
    return {"status": "success", "rechnung": rechnung}

@router.post("/webhook/zahlung-eingegangen")
async def process_incoming_payment(payload: PaymentWebhookPayload):
    if payload.invoice_id in rechnungs_speicher:
        rechnungs_speicher[payload.invoice_id]["status"] = "paid"
    return {"status": "income_registered", "invoice_id": payload.invoice_id}

@router.post("/excel/import")
async def import_excel(file: UploadFile = File(...)):
    return await ExcelImportEngine.process_excel(file)

# ============================================================================
# FASTAPI APP & LIFESPAN
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_http_client
    global_http_client = httpx.AsyncClient(timeout=10.0)
    logger.info("💰 Money Pay & RevenueAgentRoute Core online.")
    yield
    await global_http_client.aclose()
    gc.collect()

app = FastAPI(
    title="RevenueAgentRoute - Money Pay Edition",
    version="19.1.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}))
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

instrumentator = Instrumentator().instrument(app)
@app.on_event("startup")
async def _startup():
    instrumentator.expose(app)

app.include_router(router)

# ============================================================================
# START (RAILWAY PORT SUPPORT)
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
