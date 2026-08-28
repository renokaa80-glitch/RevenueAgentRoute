# ============================================================================
# REVENUEAGENTROUTE – V20.0.0 (HARDENED EDITION)
# Security: Bcrypt auth, restricted CORS, security headers, Stripe verification
# Performance: Async client pooling, semantic caching, Prometheus metrics
# ============================================================================

import asyncio
import gc
import io
import json
import logging
import os
import secrets
import uuid
import hashlib
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from collections import defaultdict

import httpx
import stripe
from fastapi import FastAPI, APIRouter, HTTPException, Request, Depends, Header, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
import jwt

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded

from prometheus_fastapi_instrumentator import Instrumentator

import pandas as pd
import openpyxl
from passlib.context import CryptContext

from dotenv import load_dotenv
load_dotenv()

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RevenueAgent_V20")

limiter = Limiter(key_func=get_remote_address)

# ===== SECURITY CONFIG =====
# FAIL FAST: No weak defaults in production
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PROD = ENVIRONMENT == "production"

GEHEIMER_SCHLUESSEL = os.getenv("SECRET_KEY", "")
if not GEHEIMER_SCHLUESSEL:
    if IS_PROD:
        raise RuntimeError("FATAL: SECRET_KEY environment variable is required in production!")
    GEHEIMER_SCHLUESSEL = "dev-only-not-for-production-use"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# Gemini API (Google AI Studio - kostenlos)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# OpenAI-compatible Gemini endpoint
AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/" if GEMINI_API_KEY else "https://api.openai.com/v1"
AI_API_KEY = GEMINI_API_KEY or OPENAI_API_KEY
STRIPE_GEHEIMER_SCHLUESSEL = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Admin credentials from env vars (no hardcoded passwords)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
# Fallback: hash a default password for dev only
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
if not ADMIN_PASSWORD_HASH:
    if IS_PROD:
        raise RuntimeError("FATAL: ADMIN_PASSWORD_HASH environment variable is required in production!")
    ADMIN_PASSWORD_HASH = pwd_context.hash("changeme")

stripe.api_key = STRIPE_GEHEIMER_SCHLUESSEL

# CORS: Restricted origins only
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")
if not ALLOWED_ORIGINS or not ALLOWED_ORIGINS[0]:
    if IS_PROD:
        ALLOWED_ORIGINS = ["https://web-production-e28af.up.railway.app"]
    else:
        ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:3000"]

# ===== GLOBALE SPEICHER =====
global_http_client: Optional[httpx.AsyncClient] = None
semantic_response_cache: Dict[str, dict] = {}
excel_imports: List[Dict] = []
lead_campaigns: List[Dict] = []
leads: List[Dict] = []
rechnungs_speicher: Dict[str, dict] = {}
task_speicher: Dict[str, dict] = {}
evolution_history: List[Dict] = []

current_version: str = "20.1.0"

# ===== AUTH (BCRYPT-BASIERT) =====
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/revenue/token")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.now(timezone.utc) + timedelta(hours=24)})
    return jwt.encode(to_encode, GEHEIMER_SCHLUESSEL, algorithm="HS256")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, GEHEIMER_SCHLUESSEL, algorithms=["HS256"])
        if payload.get("sub") != ADMIN_USERNAME:
            raise HTTPException(status_code=401, detail="Ungueltiger Token")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token abgelaufen")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Ungueltiger Token")

# ===== SYSTEM LEVEL =====
class SystemLevel(str, Enum):
    LEVEL_1 = "Level 1: 0 Euro - Zero Capital Bootstrap"
    LEVEL_2 = "Level 2: 1.000 Euro+ - Wallet & Sourcing aktiv"
    LEVEL_3 = "Level 3: 5.000 Euro+ - Worker Swarm aktiv"
    LEVEL_4 = "Level 4: 10.000 Euro+ - Global Arbitrage & Empire Mode"
    LEVEL_5 = "Level 5: 50.000 Euro+ - Autonomous Company Mode"

# ===== TREASURY WALLET =====
class TreasuryWalletEngine:
    total_bank_earnings_usd: float = 0.0
    wallet_balance_usd: float = 0.0
    current_level: SystemLevel = SystemLevel.LEVEL_1
    
    @classmethod
    def register_income(cls, amount: float):
        cls.total_bank_earnings_usd += amount
        if cls.total_bank_earnings_usd >= 50000.0:
            cls.current_level = SystemLevel.LEVEL_5
        elif cls.total_bank_earnings_usd >= 10000.0:
            cls.current_level = SystemLevel.LEVEL_4
        elif cls.total_bank_earnings_usd >= 5000.0:
            cls.current_level = SystemLevel.LEVEL_3
        elif cls.total_bank_earnings_usd >= 1000.0:
            cls.current_level = SystemLevel.LEVEL_2
        logger.info(f"Level: {cls.current_level.value}")

# ===== AGENT TYPES =====
class AgentTyp(str, Enum):
    COLD_OUTREACH = "cold_outreach_leadgen"
    SEO_AUDIT = "seo_audit_repair"
    REPUTATION_MGMT = "social_reputation_mgmt"
    AFFILIATE_NATIVE = "affiliate_niche_bot"
    PODCAST_SCOUT = "podcast_interview_scout"
    LOCAL_SEO = "google_business_local_seo"
    PROGRAMMATIC_SEO = "programmatic_content_seo"
    CRO_TESTING = "conversion_rate_opt"
    INFLUENCER_BROKER = "influencer_marketing_broker"
    NEWSLETTER_GROWTH = "newsletter_growth_curation"
    SAAS_MONITORING = "saas_uptime_monitoring"
    NOCODE_AUTOMATION = "nocode_api_integration"
    DOMAIN_BROKERAGE = "domain_brokerage_flipping"
    CYBERSECURITY_SCAN = "cybersecurity_basic_scan"
    APP_REVIEW_ANALYTICS = "app_store_review_analytics"
    CODE_AUDIT = "code_audit_refactoring"
    PRIVACY_CHECK = "datenschutz_cookie_check"
    DATA_SCRAPING_SERVICE = "data_scraping_feed_service"
    BARRIEREFREIHEIT_WCAG = "wcag_accessibility_checker"
    CLOUD_COST_OPT = "cloud_cost_optimization"
    PRICE_MONITORING = "competitor_price_monitoring"
    GRANT_SCOUT = "foerdermittel_grant_scout"
    TENDER_AGENT = "b2b_tender_ausschreibung"
    TREND_HUNTING = "trend_product_hunting"
    PATENT_CHECK = "patent_brand_precheck"
    SOURCING_SCOUT = "supplier_sourcing_scout"
    MA_FIRM_SCOUT = "ma_firm_acquisition_scout"
    EXHIBITION_HUNTER = "event_fair_lead_hunter"
    CAR_FLOCK_SCOUT = "car_deal_flock_scout"
    REAL_ESTATE_AUCTION = "real_estate_auction_scout"
    PROMPT_TEMPLATES = "prompt_engineering_templates"
    TRANSLATION_SERVICE = "multi_language_translation"
    PODCAST_REPURPOSE = "podcast_to_blog_repurpose"
    STOCK_MEDIA_CURATION = "stock_media_ai_curation"
    EMAIL_TEMPLATE_DESIGN = "email_template_design"
    EBOOK_PUBLISHER = "ebook_b2b_guide_publisher"
    VOICE_OVER_AUDIO = "voice_over_audio_gen"
    PDF_TEMPLATE_SERVICE = "pdf_gobd_template_service"
    LANDINGPAGE_COPY = "landingpage_copywriting"
    CASE_STUDY_GEN = "case_study_testimonial_gen"
    LOGISTICS_PAPER_AUDIT = "logistics_freight_paper_audit"
    DISPO_MATCHING_BOT = "dispo_truck_load_matching"
    SHIPMENT_TRACKING_BOT = "shipment_tracking_reclamation"
    CUSTOMS_DOC_GEN = "customs_import_doc_generator"
    FREIGHT_BIDDING_AGENT = "freight_board_bidding_agent"
    GLOBAL_TENDER_ENGINE = "global_tender_bidding_engine"
    GEO_OPTIMIZATION = "generative_engine_optimization"
    CRM_DATA_REPAIR = "crm_data_repair_enrichment"
    CPL_LEAD_RESELLING = "cpl_lead_reselling_arbitrage"
    NIGHTSHIFT_TRIAGE = "global_incident_nightshift_triage"
    DOMAIN_AUCTION_ARBITRAGE = "domain_auction_arbitrage"
    CLOUD_CREDIT_RESELLING = "cloud_credit_reselling"
    REALTIME_API_FEED_BROKER = "realtime_api_feed_broker"
    HIGH_TICKET_LEAD_AUCTION = "high_ticket_lead_auction"
    TRADE_SHOW_LEAD_HARVEST = "trade_show_lead_harvest"
    GEO_AI_VISIBILITY_AUDIT = "geo_ai_visibility_audit"
    SAAS_LICENSE_ARBITRAGE = "saas_license_arbitrage"
    B2B_CRM_ENRICHMENT_BOT = "b2b_crm_enrichment_bot"
    PROGRAMMATIC_NEWSLETTER_ADS = "programmatic_newsletter_ads"
    DECENTRALIZED_DATA_YIELD = "decentralized_data_yield"
    ENTERPRISE_SOFTWARE_DISCOUNT = "enterprise_software_discount"
    PUBLIC_MICRO_RFP_DISCOVERY = "public_micro_rfp_discovery"
    TRADEMARK_EXPIRATION_SCOUT = "trademark_expiration_scout"
    COMPETITOR_HIRING_ANALYTICS = "competitor_hiring_analytics"
    CLOUD_WASTE_AUDIT = "cloud_waste_audit"
    ACCESSIBILITY_PROTECTION_WCAG = "accessibility_protection_wcag"
    REPUTATION_DEFENSE_REPAIR = "reputation_defense_repair"
    PAY_PER_CALL_ARBITRAGE = "pay_per_call_arbitrage"
    CART_RECOVERY_WINBACK = "cart_recovery_winback"
    GEO_KNOWLEDGE_GRAPH_ENTRY = "geo_knowledge_graph_entry"

# ===== GLOBAL TIMEZONE ENGINE =====
class GlobalTimezoneEngine:
    @staticmethod
    def get_active_hubs() -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        us_h = (now_utc.hour - 5) % 24
        eu_h = (now_utc.hour + 1) % 24
        asia_h = (now_utc.hour + 8) % 24
        
        active = "EU (Europe)"
        if 8 <= us_h <= 18:
            active = "US (Americas)"
        elif 8 <= asia_h <= 18:
            active = "APAC (Asia-Pacific)"
        
        return {
            "current_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "primary_active_region": active,
            "hubs": {
                "US": {"time": f"{us_h:02d}:00 EST", "status": "ACTIVE" if 8 <= us_h <= 18 else "STANDBY"},
                "EU": {"time": f"{eu_h:02d}:00 CET", "status": "ACTIVE" if 8 <= eu_h <= 18 else "STANDBY"},
                "APAC": {"time": f"{asia_h:02d}:00 SGT", "status": "ACTIVE" if 8 <= asia_h <= 18 else "STANDBY"}
            }
        }

# ===== SMART AI ROUTER =====
class SmartAIRouter:
    CHEAP_MODEL = "gemini-1.5-flash" if GEMINI_API_KEY else "gpt-4o-mini"
    ADVANCED_MODEL = "gemini-1.5-pro" if GEMINI_API_KEY else "gpt-4o"
    
    @classmethod
    def get_model_for_sparte(cls, sparte: str) -> str:
        high_complexity = [
            "global_tender_bidding_engine", "code_audit_refactoring",
            "freight_board_bidding_agent", "self_evolution"
        ]
        return cls.ADVANCED_MODEL if sparte in high_complexity else cls.CHEAP_MODEL
    
    @classmethod
    async def call_llm_efficient(cls, prompt: str, sparte: str) -> str:
        # SHA-256 statt MD5 fuer sicherere Cache-Keys
        cache_key = hashlib.sha256((sparte + ":" + prompt).encode()).hexdigest()
        cached = semantic_response_cache.get(cache_key)
        if cached and (datetime.now(timezone.utc) - cached["time"]).total_seconds() < 3600:
            return cached["response"]
        
        model = cls.get_model_for_sparte(sparte)
        if not AI_API_KEY or global_http_client is None:
            simulated = f"Simulierte KI-Optimierung fuer {sparte} [Modell: {model}]."
            semantic_response_cache[cache_key] = {"response": simulated, "time": datetime.now(timezone.utc)}
            return simulated
        
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Praezise B2B-Antworten. Keine Fuellwoerter."},
                {"role": "user", "content": prompt[:2000]}  # Input laenge begrenzen
            ],
            "max_tokens": 400,
            "temperature": 0.2
        }
        
        try:
            async with global_http_client.post(f"{AI_BASE_URL}chat/completions", headers=headers, json=payload, timeout=15.0) as res:
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"]
                    semantic_response_cache[cache_key] = {"response": text, "time": datetime.now(timezone.utc)}
                    return text
                return f"API-Fehler: {res.status_code}"
        except Exception as e:
            logger.error(f"LLM call failed: {type(e).__name__}")
            return f"Fehler: {type(e).__name__}"

# ===== SELF EVOLUTION ENGINE =====
class SelfEvolutionEngine:
    @classmethod
    async def analyze_and_improve(cls) -> Dict:
        prompt = "Analysiere den Code. Finde 3 Verbesserungen."
        verbesserung = await SmartAIRouter.call_llm_efficient(prompt, "self_evolution")
        evolution_history.append({
            "zeit": datetime.now(timezone.utc).isoformat(),
            "verbesserung": verbesserung,
            "version": current_version
        })
        return {"status": "analysiert", "verbesserung": verbesserung}
    
    @classmethod
    async def deploy_upgrade(cls, code: str) -> Dict:
        global current_version
        # SICHERHEIT: Code-Laenge begrenzen, keine echte Code-Ausfuehrung
        if len(code) > 5000:
            raise HTTPException(status_code=400, detail="Code zu lang (max 5000 Zeichen)")
        version_parts = current_version.split(".")
        new_minor = int(version_parts[1]) + 1
        current_version = f"{version_parts[0]}.{new_minor}.0"
        return {"status": "deployed", "new_version": current_version}

# ===== MULTI-AGENT ORCHESTRATOR =====
class LeadGenAgent:
    async def analysieren(self, aufgabe: str) -> str:
        return await SmartAIRouter.call_llm_efficient(
            f"Analysiere Zielgruppe fuer: {aufgabe[:500]}",
            "cold_outreach_leadgen"
        )

class ContentAgent:
    async def erstellen(self, strategie: str) -> str:
        return await SmartAIRouter.call_llm_efficient(
            f"Erstelle B2B-Copy fuer Strategie: {strategie[:500]}",
            "landingpage_copywriting"
        )

class SEOAgent:
    async def optimieren(self, inhalt: str) -> str:
        return await SmartAIRouter.call_llm_efficient(
            f"Optimiere fuer GEO & SEO: {inhalt[:500]}",
            "seo_audit_repair"
        )

class MultiAgentOrchestrator:
    def __init__(self):
        self.lead = LeadGenAgent()
        self.content = ContentAgent()
        self.seo = SEOAgent()
    
    async def orchestrate(self, aufgabe: str) -> Dict[str, Any]:
        strategie = await self.lead.analysieren(aufgabe)
        inhalt = await self.content.erstellen(strategie)
        optimiert = await self.seo.optimieren(inhalt)
        return {
            "status": "success",
            "strategie": strategie,
            "inhalt": inhalt,
            "optimiert": optimiert
        }

orchestrator_engine = MultiAgentOrchestrator()

# ===== EXCEL IMPORT ENGINE =====
class ExcelImportEngine:
    @staticmethod
    async def process_excel(file: UploadFile) -> Dict:
        if not file.filename.endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="Nur Excel-Dateien (.xlsx, .xls) erlaubt.")
        
        # Dateigroesse begrenzen (10MB max)
        contents = await file.read()
        if len(contents) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Datei zu gross (max 10MB)")

        try:
            df = pd.read_excel(io.BytesIO(contents), engine="openpyxl")
            
            df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]
            records = df.to_dict(orient="records")
            
            import_record = {
                "filename": file.filename,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rows": len(records),
                "columns": list(df.columns),
                "data": records[:100]  # Max 100 Records speichern
            }
            excel_imports.append(import_record)
            
            gc.collect()
            
            return {
                "status": "success",
                "imported_rows": len(records),
                "columns": list(df.columns),
                "message": f"Excel-Datei {file.filename} erfolgreich importiert."
            }
            
        except Exception as e:
            logger.error(f"Excel-Import Fehler: {type(e).__name__}")
            raise HTTPException(status_code=500, detail="Fehler beim Verarbeiten der Excel-Datei")

# ===== LEAD GENERATION BOTS =====
class LeadGenerationBots:
    @classmethod
    async def create_campaign(cls, name: str, target_industry: str, budget: float) -> Dict:
        campaign = {
            "id": f"camp_{uuid.uuid4().hex[:8]}",
            "name": name,
            "target_industry": target_industry,
            "budget": budget,
            "status": "active",
            "leads_found": 0,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        lead_campaigns.append(campaign)
        await cls.run_campaign(campaign["id"])
        return campaign
    
    @classmethod
    async def run_campaign(cls, campaign_id: str) -> Dict:
        campaign = next((c for c in lead_campaigns if c["id"] == campaign_id), None)
        if not campaign:
            return {"status": "error", "message": "Kampagne nicht gefunden"}
        
        prompt = f"Suche nach potenziellen B2B-Kunden in der Branche {campaign['target_industry']}"
        result = await SmartAIRouter.call_llm_efficient(prompt, "lead_generation")
        
        leads_created = 0
        for lead in result.split("\n")[:10]:
            if len(lead.strip()) > 5:
                leads.append({
                    "id": f"lead_{uuid.uuid4().hex[:8]}",
                    "campaign_id": campaign_id,
                    "data": lead,
                    "status": "new",
                    "created_at": datetime.now(timezone.utc).isoformat()
                })
                leads_created += 1
        
        campaign["leads_found"] = leads_created
        campaign["status"] = "completed"
        
        return {"status": "completed", "leads_found": leads_created}
    
    @classmethod
    async def get_leads(cls, status: Optional[str] = None) -> List[Dict]:
        if status:
            return [l for l in leads if l["status"] == status]
        return leads

# ================================================================
# PYDANTIC MODELS
# ================================================================

class RechnungErstellen(BaseModel):
    kunden_email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
    betrag: float = Field(..., gt=0, le=100000.0)
    beschreibung: str = Field(..., min_length=5, max_length=200)
    faelligkeit_tage: int = Field(14, ge=1, le=90)

class WalletDepositRequest(BaseModel):
    amount_usd: float = Field(..., gt=0, le=100000.0)

class PaymentWebhookPayload(BaseModel):
    invoice_id: str = Field(..., max_length=100)
    paid_amount: float = Field(..., gt=0, le=100000.0)

class TaskAnfrage(BaseModel):
    sparte: AgentTyp
    ziel_branche: str = Field(..., max_length=200)

class OrchestrateAnfrage(BaseModel):
    aufgabe: str = Field(..., max_length=1000)

class LeadCampaignRequest(BaseModel):
    name: str = Field(..., max_length=200)
    target_industry: str = Field(..., max_length=200)
    budget: float = Field(100.0, gt=0, le=100000.0)

class EvolutionDeployRequest(BaseModel):
    code: str = Field(..., max_length=5000)

# ================================================================
# SECURITY HEADERS MIDDLEWARE
# ================================================================

async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if IS_PROD:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return response

# ================================================================
# ROUTER
# ================================================================

router = APIRouter(prefix="/api/revenue", tags=["RevenueAgent_V20"])

# ===== AUTH =====
@router.post("/token")
@limiter.limit("5/minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != ADMIN_USERNAME or not verify_password(form_data.password, ADMIN_PASSWORD_HASH):
        raise HTTPException(status_code=401, detail="Falscher Benutzername oder Passwort")
    token = create_access_token({"sub": ADMIN_USERNAME, "role": "admin"})
    return {"access_token": token, "token_type": "bearer"}

# ===== HEALTH =====
@router.get("/health")
async def health_check():
    time_info = GlobalTimezoneEngine.get_active_hubs()
    return {
        "status": "healthy",
        "version": current_version,
        "sparten_anzahl": len(AgentTyp),
        "total_bank_earnings_usd": TreasuryWalletEngine.total_bank_earnings_usd,
        "wallet_balance_usd": TreasuryWalletEngine.wallet_balance_usd,
        "level": TreasuryWalletEngine.current_level.value,
        "primary_active_region": time_info["primary_active_region"]
    }

# ===== WALLET =====
@router.get("/wallet/status")
async def get_wallet_status(user: dict = Depends(get_current_user)):
    return {
        "total_bank_earnings_usd": TreasuryWalletEngine.total_bank_earnings_usd,
        "wallet_balance_usd": TreasuryWalletEngine.wallet_balance_usd,
        "current_level": TreasuryWalletEngine.current_level.value
    }

@router.post("/wallet/einzahlen")
@limiter.limit("3/minute")
async def deposit_to_wallet(request: Request, req: WalletDepositRequest, user: dict = Depends(get_current_user)):
    TreasuryWalletEngine.wallet_balance_usd += req.amount_usd
    return {"status": "success", "new_wallet_balance_usd": TreasuryWalletEngine.wallet_balance_usd}

# ===== TIMEZONES =====
@router.get("/dashboard/timezones")
async def get_timezones():
    return GlobalTimezoneEngine.get_active_hubs()

# ===== RECHNUNGEN =====
@router.post("/rechnung/erstellen")
@limiter.limit("10/minute")
async def rechnung_erstellen(request: Request, anfrage: RechnungErstellen, user: dict = Depends(get_current_user)):
    rechnungs_id = f"inv_{uuid.uuid4().hex[:8]}"
    faellig = datetime.now(timezone.utc) + timedelta(days=anfrage.faelligkeit_tage)
    
    rechnung = {
        "id": rechnungs_id,
        "kunden_email": anfrage.kunden_email,
        "betrag": anfrage.betrag,
        "beschreibung": anfrage.beschreibung,
        "status": "sent",
        "faelligkeitsdatum": faellig.isoformat(),
        "zahlungs_link": f"https://pay.revenueagentroute.com/{rechnungs_id}"
    }
    rechnungs_speicher[rechnungs_id] = rechnung
    return {"status": "success", "rechnung": rechnung}

# ===== STRIPE WEBHOOK (mit Signatur-Verifikation) =====
@router.post("/webhook/zahlung-eingegangen")
async def process_incoming_payment(request: Request):
    # Stripe Signatur verifizieren wenn in Produktion
    if IS_PROD and STRIPE_WEBHOOK_SECRET:
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=401, detail="Ungueltige Stripe-Signatur")
        invoice_id = event.get("data", {}).get("object", {}).get("id", "")
        paid_amount = event.get("data", {}).get("object", {}).get("amount_total", 0) / 100
    else:
        body = await request.json()
        invoice_id = body.get("invoice_id", "")
        paid_amount = body.get("paid_amount", 0)
    
    if invoice_id in rechnungs_speicher:
        rechnungs_speicher[invoice_id]["status"] = "paid"
    
    TreasuryWalletEngine.register_income(paid_amount)
    return {
        "status": "income_registered",
        "total_bank_earnings_usd": TreasuryWalletEngine.total_bank_earnings_usd,
        "current_level": TreasuryWalletEngine.current_level.value
    }

# ===== EXCEL =====
@router.post("/excel/import")
@limiter.limit("5/minute")
async def import_excel(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    result = await ExcelImportEngine.process_excel(file)
    return result

# ===== LEADS =====
@router.post("/leads/campaign")
@limiter.limit("5/minute")
async def create_lead_campaign(request: Request, req: LeadCampaignRequest, user: dict = Depends(get_current_user)):
    result = await LeadGenerationBots.create_campaign(req.name, req.target_industry, req.budget)
    return {"status": "campaign_created", "result": result}

@router.get("/leads/all")
async def get_all_leads(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    leads_result = await LeadGenerationBots.get_leads(status)
    return {"leads": leads_result, "count": len(leads_result)}

# ===== TASKS =====
@router.post("/task/starten")
@limiter.limit("10/minute")
async def task_starten(request: Request, req: TaskAnfrage, user: dict = Depends(get_current_user)):
    ergebnis = await SmartAIRouter.call_llm_efficient(
        f"Fuehre Sparte {req.sparte.value} fuer {req.ziel_branche} aus.",
        req.sparte.value
    )
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task_speicher[task_id] = {
        "id": task_id,
        "sparte": req.sparte.value,
        "ziel_branche": req.ziel_branche,
        "ergebnis": ergebnis,
        "status": "completed"
    }
    return {"status": "completed", "task_id": task_id, "ergebnis": ergebnis}

# ===== SPARTEN =====
@router.get("/sparten/alle")
async def alle_sparten_auflisten():
    return {"gesamt_sparten": len(AgentTyp), "sparten_liste": [s.value for s in AgentTyp]}

# ===== ORCHESTRATE =====
@router.post("/orchestrate/team-task")
@limiter.limit("5/minute")
async def orchestrate_team_task(request: Request, req: OrchestrateAnfrage, user: dict = Depends(get_current_user)):
    ergebnis = await orchestrator_engine.orchestrate(req.aufgabe)
    return ergebnis

# ===== EVOLUTION =====
@router.post("/evolution/analyze")
@limiter.limit("2/minute")
async def evolution_analysieren(request: Request, user: dict = Depends(get_current_user)):
    return await SelfEvolutionEngine.analyze_and_improve()

@router.post("/evolution/deploy")
@limiter.limit("2/minute")
async def evolution_deployen(request: Request, req: EvolutionDeployRequest, user: dict = Depends(get_current_user)):
    return await SelfEvolutionEngine.deploy_upgrade(req.code)

@router.get("/evolution/history")
async def evolution_history_abrufen(user: dict = Depends(get_current_user)):
    return {"evolution": evolution_history[-20:]}

# ================================================================
# FASTAPI APP
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_http_client
    global_http_client = httpx.AsyncClient(timeout=15.0)
    logger.info(f"🚀 RevenueAgentRoute V{current_version} gestartet [{ENVIRONMENT}]")
    yield
    await global_http_client.aclose()
    gc.collect()

app = FastAPI(
    title="RevenueAgentRoute V20.1.0",
    version=current_version,
    description="B2B Revenue Operating System - Hardened Edition",
    lifespan=lifespan
)

# Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}))
app.add_middleware(SlowAPIMiddleware)

# Security Headers Middleware
app.middleware("http")(add_security_headers)

# CORS: Restricted
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Prometheus Metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000)

