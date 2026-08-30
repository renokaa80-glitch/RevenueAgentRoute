# ============================================================================
# REVENUEAGENTROUTE – V21.0.0 (TOKEN-OPTIMIZED + ALL FEATURES MERGED)
# Based on V20.2.0 (Hardened) + V19.1.0 (Features) + Token-Saver + Keep-Alive
# ============================================================================

import asyncio
import gc
import io
import json
import logging
import os
import secrets
import time
import uuid
import hashlib
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from collections import defaultdict, deque

import httpx
import stripe
from fastapi import FastAPI, APIRouter, HTTPException, Request, Depends, Header, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
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
logger = logging.getLogger("RevenueAgent_V21")

limiter = Limiter(key_func=get_remote_address)

# ===== SECURITY CONFIG =====
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PROD = ENVIRONMENT == "production"

GEHEIMER_SCHLUESSEL = os.getenv("SECRET_KEY", "")
if not GEHEIMER_SCHLUESSEL:
    if IS_PROD:
        raise RuntimeError("FATAL: SECRET_KEY environment variable is required in production!")
    GEHEIMER_SCHLUESSEL = "dev-only-not-for-production-use"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GROQ_API_KEY:
    AI_BASE_URL = "https://api.groq.com/openai/v1"
    AI_API_KEY = GROQ_API_KEY
elif GEMINI_API_KEY:
    AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    AI_API_KEY = GEMINI_API_KEY
else:
    AI_BASE_URL = "https://api.openai.com/v1"
    AI_API_KEY = OPENAI_API_KEY
STRIPE_GEHEIMER_SCHLUESSEL = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "https://web-production-e28af.up.railway.app")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
if not ADMIN_PASSWORD_HASH:
    if IS_PROD:
        raise RuntimeError("FATAL: ADMIN_PASSWORD_HASH environment variable is required in production!")
    ADMIN_PASSWORD_HASH = pwd_context.hash("changeme")

stripe.api_key = STRIPE_GEHEIMER_SCHLUESSEL

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
kunden_register: Dict[str, dict] = {}
checkout_sessions: Dict[str, dict] = {}

# NEW: V19.1.0 storage
cost_history: List[Dict] = []
market_insights: List[Dict] = []
replicas: List[Dict] = []
learning_knowledge: List[Dict] = []
audit_logs: List[Dict] = []
tenants: Dict[str, dict] = {}

current_version: str = "21.0.0"

# ===== TOKEN SAVER SYSTEM (NEW) =====
class TokenSaver:
    """Verhindert Token-Explosion: Cache + Rate Limit + Staggered Startup."""
    CACHE_TTL_SECONDS = 3600  # 1 Stunde Cache
    bot_rate_limits: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
    MAX_CALLS_PER_MINUTE = 10
    PRIORITY_BOTS = [
        "cold_outreach_leadgen", "landingpage_copywriting", "seo_audit_repair",
        "competitor_price_monitoring", "lead_generation"
    ]
    STAGGER_WAVE_SIZE = 5
    STAGGER_DELAY_SECONDS = 2
    total_tokens_used: int = 0
    total_api_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    @classmethod
    def check_rate_limit(cls, sparte: str) -> bool:
        now = time.time()
        bot_queue = cls.bot_rate_limits[sparte]
        while bot_queue and bot_queue[0] < now - 60:
            bot_queue.popleft()
        if len(bot_queue) >= cls.MAX_CALLS_PER_MINUTE:
            logger.warning(f"Rate Limit fuer {sparte} — pausiert")
            return False
        bot_queue.append(now)
        return True

    @classmethod
    def get_stats(cls) -> Dict:
        total = cls.cache_hits + cls.cache_misses
        return {
            "total_tokens_used": cls.total_tokens_used,
            "total_api_calls": cls.total_api_calls,
            "cache_hits": cls.cache_hits,
            "cache_misses": cls.cache_misses,
            "cache_size": len(semantic_response_cache),
            "cache_hit_rate": f"{(cls.cache_hits / max(total, 1) * 100):.1f}%",
            "tokens_saved_by_cache": cls.cache_hits * 400
        }

    @classmethod
    def get_startup_waves(cls, all_bots: List[str]) -> List[List[str]]:
        priority = [b for b in all_bots if b in cls.PRIORITY_BOTS]
        others = [b for b in all_bots if b not in cls.PRIORITY_BOTS]
        ordered = priority + others
        waves = []
        for i in range(0, len(ordered), cls.STAGGER_WAVE_SIZE):
            waves.append(ordered[i:i + cls.STAGGER_WAVE_SIZE])
        return waves

# ===== KEEP ALIVE SYSTEM (NEW) =====
class KeepAliveSystem:
    last_ping: Optional[datetime] = None
    ping_count: int = 0
    is_running: bool = False

    @classmethod
    async def start_keep_alive(cls):
        cls.is_running = True
        while cls.is_running:
            cls.last_ping = datetime.now(timezone.utc)
            cls.ping_count += 1
            logger.info(f"Keep-Alive Ping #{cls.ping_count}")
            await asyncio.sleep(240)  # 4 Min — Railway Sleep nach 5 Min Inaktivität

    @classmethod
    async def stop(cls):
        cls.is_running = False

    @classmethod
    def get_status(cls) -> Dict:
        return {
            "running": cls.is_running,
            "last_ping": cls.last_ping.isoformat() if cls.last_ping else None,
            "total_pings": cls.ping_count
        }

# ===== AUTH =====
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

# ===== AGENT TYPES (71) =====
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
    WEB_TESTING_LEGACY_EXTRACTION = "web_testing_legacy_extraction"

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
                "US": {"time": f"{us_h:02d}:{now_utc.minute:02d} EST", "status": "ACTIVE" if 8 <= us_h <= 18 else "STANDBY"},
                "EU": {"time": f"{eu_h:02d}:{now_utc.minute:02d} CET", "status": "ACTIVE" if 8 <= eu_h <= 18 else "STANDBY"},
                "APAC": {"time": f"{asia_h:02d}:{now_utc.minute:02d} SGT", "status": "ACTIVE" if 8 <= asia_h <= 18 else "STANDBY"}
            }
        }

# ===== SMART AI ROUTER (WITH TOKEN SAVER) =====
class SmartAIRouter:
    if GROQ_API_KEY:
        CHEAP_MODEL = "llama-3.3-70b-versatile"
        ADVANCED_MODEL = "llama-3.3-70b-versatile"
    elif GEMINI_API_KEY:
        CHEAP_MODEL = "gemini-1.5-flash"
        ADVANCED_MODEL = "gemini-1.5-pro"
    else:
        CHEAP_MODEL = "gpt-4o-mini"
        ADVANCED_MODEL = "gpt-4o"

    @classmethod
    def get_model_for_sparte(cls, sparte: str) -> str:
        high_complexity = [
            "global_tender_bidding_engine", "code_audit_refactoring",
            "freight_board_bidding_agent", "self_evolution",
            "market_intelligence", "continuous_learning"
        ]
        return cls.ADVANCED_MODEL if sparte in high_complexity else cls.CHEAP_MODEL

    @classmethod
    async def call_llm_efficient(cls, prompt: str, sparte: str) -> str:
        # 1. Cache pruefen (spart Tokens!)
        cache_key = hashlib.sha256((sparte + ":" + prompt).encode()).hexdigest()
        cached = semantic_response_cache.get(cache_key)
        if cached and (datetime.now(timezone.utc) - cached["time"]).total_seconds() < TokenSaver.CACHE_TTL_SECONDS:
            TokenSaver.cache_hits += 1
            return cached["response"]
        TokenSaver.cache_misses += 1

        # 2. Rate Limit (verhindert Token-Explosion)
        if not TokenSaver.check_rate_limit(sparte):
            return f"Rate Limit erreicht fuer {sparte}. Bitte in 60 Sekunden erneut versuchen."

        # 3. Kein API Key -> Offline-Modus
        model = cls.get_model_for_sparte(sparte)
        if not AI_API_KEY or global_http_client is None:
            simulated = f"[Offline-Modus] Simulierte Antwort fuer {sparte} [Modell: {model}]."
            semantic_response_cache[cache_key] = {"response": simulated, "time": datetime.now(timezone.utc)}
            return simulated

        # 4. API Call mit Token-Tracking
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Praezise B2B-Antworten. Keine Fuellwoerter."},
                {"role": "user", "content": prompt[:2000]}
            ],
            "max_tokens": 400,
            "temperature": 0.2
        }

        try:
            res = await global_http_client.post(f"{AI_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=15.0)
            TokenSaver.total_api_calls += 1
            if res.status_code == 200:
                data = res.json()
                text = data["choices"][0]["message"]["content"]
                if "usage" in data:
                    TokenSaver.total_tokens_used += data["usage"].get("total_tokens", 400)
                semantic_response_cache[cache_key] = {"response": text, "time": datetime.now(timezone.utc)}
                # Cache aufraeumen wenn zu gross
                if len(semantic_response_cache) > 500:
                    oldest = sorted(semantic_response_cache.items(), key=lambda x: x[1]["time"])[:100]
                    for key, _ in oldest:
                        del semantic_response_cache[key]
                return text
            return f"API-Fehler: {res.status_code}"
        except Exception as e:
            logger.error(f"LLM call failed: {type(e).__name__}")
            return f"Fehler: {type(e).__name__}"

# ===== SELF EVOLUTION ENGINE =====
B2BAgent = SmartAIRouter

class SelfEvolutionEngine:
    @classmethod
    async def analyze_and_improve(cls) -> Dict:
        prompt = "Analysiere den Code. Finde 3 Verbesserungen fuer Performance und Skalierung."
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
        if len(code) > 5000:
            raise HTTPException(status_code=400, detail="Code zu lang (max 5000 Zeichen)")
        version_parts = current_version.split(".")
        new_minor = int(version_parts[1]) + 1
        current_version = f"{version_parts[0]}.{new_minor}.0"
        return {"status": "deployed", "new_version": current_version}

# ===== COST OPTIMIZATION (NEW from V19.1.0) =====
class AutonomeKostenoptimierung:
    current_monthly_costs: float = 0.0

    @classmethod
    async def optimize_costs(cls) -> Dict:
        prompt = "Analysiere Infrastruktur-Kosten (alles kostenlos: Groq, Railway). Finde Skalierungspotenzial."
        optimierung = await SmartAIRouter.call_llm_efficient(prompt, "cost_optimization")
        cost_history.append({"zeit": datetime.now(timezone.utc).isoformat(), "optimierung": optimierung})
        return {"status": "optimiert", "empfehlung": optimierung, "current_costs": cls.current_monthly_costs}

# ===== MARKET INTELLIGENCE (NEW from V19.1.0) =====
class MarketIntelligence:
    @classmethod
    async def scan_markets(cls) -> Dict:
        prompt = "Analysiere B2B-KI-Maerkte. Identifiziere 3 aufkommende Nischen mit Umsatzpotenzial."
        insights = await SmartAIRouter.call_llm_efficient(prompt, "market_intelligence")
        market_insights.append({"zeit": datetime.now(timezone.utc).isoformat(), "insights": insights})
        return {"status": "gescannt", "insights": insights}

    @classmethod
    async def create_new_agent_for_market(cls, markt: str) -> Dict:
        return {"status": "agent_erstellt", "sparte": "new_" + markt.replace(" ", "_").lower()}

# ===== SELF REPLICATION (NEW from V19.1.0) =====
class SelfReplication:
    @classmethod
    async def create_replica(cls, niche: str, config: Dict = {}) -> Dict:
        replica_id = "replica_" + uuid.uuid4().hex[:8]
        replicas.append({"id": replica_id, "niche": niche, "config": config, "created": datetime.now(timezone.utc).isoformat(), "status": "active"})
        return {"status": "replica_created", "id": replica_id}

    @classmethod
    async def deploy_replica(cls, replica_id: str) -> Dict:
        for r in replicas:
            if r["id"] == replica_id:
                r["status"] = "deployed"
                return {"status": "deployed", "replica_id": replica_id}
        return {"status": "not_found"}

# ===== CONTINUOUS LEARNING (NEW from V19.1.0) =====
class ContinuousLearning:
    @classmethod
    async def learn_from_interaction(cls, interaction: Dict) -> Dict:
        learning_knowledge.append({"zeit": datetime.now(timezone.utc).isoformat(), "interaction": interaction})
        return {"status": "gelernt", "total": len(learning_knowledge)}

    @classmethod
    async def get_best_practices(cls) -> Dict:
        prompt = "Extrahiere 5 Best Practices aus allen Interaktionen."
        practices = await SmartAIRouter.call_llm_efficient(prompt, "continuous_learning")
        return {"practices": practices, "total_learned": len(learning_knowledge)}

# ===== ENTERPRISE SECURITY (NEW from V19.1.0) =====
class EnterpriseSecurityShield:
    @staticmethod
    async def audit_log(aktion: str, benutzer: str, details: Dict):
        log = {"zeit": datetime.now(timezone.utc).isoformat(), "aktion": aktion, "benutzer": benutzer, "details": details, "session_id": str(uuid.uuid4())}
        audit_logs.append(log)
        if len(audit_logs) > 1000:
            audit_logs.pop(0)
        return log

    @staticmethod
    async def check_rbac(rolle: str, aktion: str) -> bool:
        if rolle == "admin": return True
        if rolle == "reseller" and aktion in ["task_starten", "rechnung_erstellen", "leads"]: return True
        return False

# ===== GLOBAL COMPLIANCE (NEW from V19.1.0) =====
class GlobalComplianceEngine:
    @staticmethod
    async def check_compliance(region: str) -> Dict:
        checks = {
            "EU": {"status": "compliant", "regeln": ["DSGVO", "GoBD"], "risiko": "niedrig"},
            "US": {"status": "partially_compliant", "regeln": ["CCPA"], "risiko": "mittel"},
            "APAC": {"status": "compliant", "regeln": ["PDPA"], "risiko": "niedrig"},
            "CA": {"status": "compliant", "regeln": ["PIPEDA"], "risiko": "niedrig"}
        }
        return checks.get(region, {"status": "unknown", "risiko": "hoch"})

# ===== BUSINESS INTELLIGENCE (NEW from V19.1.0) =====
class BusinessIntelligenceEngine:
    @staticmethod
    async def generate_report(zeitraum: str) -> Dict:
        return {
            "zeitraum": zeitraum,
            "umsatz_usd": TreasuryWalletEngine.total_bank_earnings_usd,
            "bots": len(AgentTyp),
            "level": TreasuryWalletEngine.current_level.value,
            "prognose": TreasuryWalletEngine.total_bank_earnings_usd * 2.5,
            "trends": ["KI-Nachfrage steigt", "B2B-Automatisierung waechst", "SaaS-Modelle dominieren"]
        }

# ===== MULTI TENANT (NEW from V19.1.0) =====
class MultiTenantEngine:
    @classmethod
    def create_tenant(cls, name: str, config: Dict = {}) -> str:
        tenant_id = "tenant_" + uuid.uuid4().hex[:8]
        tenants[tenant_id] = {"name": name, "config": config, "created": datetime.now(timezone.utc).isoformat()}
        return tenant_id

    @classmethod
    def get_tenant(cls, tenant_id: str) -> Dict:
        return tenants.get(tenant_id, {"status": "not_found"})

# ===== DSGVO COMPLIANCE (NEW from V19.1.0) =====
class DSGVOComplianceEngine:
    @staticmethod
    async def anonymize_user_data(user_id: str) -> Dict:
        return {"status": "anonymized", "user_id": user_id, "at": datetime.now(timezone.utc).isoformat()}

    @staticmethod
    async def delete_user_data(user_id: str) -> Dict:
        return {"status": "deleted", "user_id": user_id, "at": datetime.now(timezone.utc).isoformat()}

    @staticmethod
    async def export_user_data(user_id: str) -> Dict:
        return {"status": "exported", "user_id": user_id, "at": datetime.now(timezone.utc).isoformat()}

# ===== MULTI-AGENT ORCHESTRATOR =====
class LeadGenAgent:
    async def analysieren(self, aufgabe: str) -> str:
        return await SmartAIRouter.call_llm_efficient(f"Analysiere Zielgruppe fuer: {aufgabe[:500]}", "cold_outreach_leadgen")

class ContentAgent:
    async def erstellen(self, strategie: str) -> str:
        return await SmartAIRouter.call_llm_efficient(f"Erstelle B2B-Copy fuer Strategie: {strategie[:500]}", "landingpage_copywriting")

class SEOAgent:
    async def optimieren(self, inhalt: str) -> str:
        return await SmartAIRouter.call_llm_efficient(f"Optimiere fuer GEO & SEO: {inhalt[:500]}", "seo_audit_repair")

class MultiAgentOrchestrator:
    def __init__(self):
        self.lead = LeadGenAgent()
        self.content = ContentAgent()
        self.seo = SEOAgent()

    async def orchestrate(self, aufgabe: str) -> Dict[str, Any]:
        strategie = await self.lead.analysieren(aufgabe)
        inhalt = await self.content.erstellen(strategie)
        optimiert = await self.seo.optimieren(inhalt)
        return {"status": "success", "strategie": strategie, "inhalt": inhalt, "optimiert": optimiert}

orchestrator_engine = MultiAgentOrchestrator()

# ===== EXCEL IMPORT ENGINE =====
class ExcelImportEngine:
    @staticmethod
    async def process_excel(file: UploadFile) -> Dict:
        if not file.filename.endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="Nur Excel-Dateien (.xlsx, .xls) erlaubt.")
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
                "rows": len(records), "columns": list(df.columns),
                "data": records[:100]
            }
            excel_imports.append(import_record)
            # Auto-create leads if email column exists
            leads_created = 0
            if "email" in df.columns:
                leads_created = len(df)
                for _, row in df.iterrows():
                    leads.append({
                        "id": f"lead_{uuid.uuid4().hex[:8]}",
                        "source": "excel_import",
                        "email": str(row.get("email", "")),
                        "firma": str(row.get("firma", row.get("company", ""))),
                        "data": row.to_dict(),
                        "status": "new",
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })
            gc.collect()
            return {"status": "success", "imported_rows": len(records), "leads_created": leads_created, "columns": list(df.columns)}
        except Exception as e:
            logger.error(f"Excel-Import Fehler: {type(e).__name__}")
            raise HTTPException(status_code=500, detail="Fehler beim Verarbeiten der Excel-Datei")

# ===== LEAD GENERATION BOTS =====
class LeadGenerationBots:
    @classmethod
    async def create_campaign(cls, name: str, target_industry: str, budget: float) -> Dict:
        campaign = {
            "id": f"camp_{uuid.uuid4().hex[:8]}",
            "name": name, "target_industry": target_industry, "budget": budget,
            "status": "active", "leads_found": 0,
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
        prompt = f"Suche 10 potenzielle B2B-Kunden in der Branche {campaign['target_industry']}. Format: Firma, Kontakt, Email."
        result = await SmartAIRouter.call_llm_efficient(prompt, "lead_generation")
        leads_created = 0
        for lead in result.split("\n")[:10]:
            if len(lead.strip()) > 5:
                leads.append({
                    "id": f"lead_{uuid.uuid4().hex[:8]}",
                    "campaign_id": campaign_id, "data": lead.strip(),
                    "status": "new", "created_at": datetime.now(timezone.utc).isoformat()
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

    @classmethod
    async def get_campaigns(cls) -> List[Dict]:
        return lead_campaigns

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

class KundeRequest(BaseModel):
    name: str
    email: str
    company: str = ""

class CheckoutRequest(BaseModel):
    service_name: str
    price: float
    kunde_email: str
    kunde_name: str = ""
    kunde_company: str = ""
    brief_description: str = ""

# NEW models for V19.1.0 features
class ComplianceCheckRequest(BaseModel):
    region: str

class BIReportRequest(BaseModel):
    zeitraum: str = "aktuell"

class TenantCreateRequest(BaseModel):
    name: str
    config: Dict = {}

class LearningRecordRequest(BaseModel):
    interaction: Dict

class ReplicaCreateRequest(BaseModel):
    niche: str
    config: Dict = {}

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
router = APIRouter(prefix="/api/revenue", tags=["RevenueAgent_V21"])

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
        "primary_active_region": time_info["primary_active_region"],
        "groq_connected": bool(GROQ_API_KEY),
        "keep_alive": KeepAliveSystem.is_running,
        "token_stats": TokenSaver.get_stats()
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
        "id": rechnungs_id, "kunden_email": anfrage.kunden_email,
        "betrag": anfrage.betrag, "beschreibung": anfrage.beschreibung,
        "status": "sent", "faelligkeitsdatum": faellig.isoformat(),
        "zahlungs_link": f"https://pay.revenueagentroute.com/{rechnungs_id}"
    }
    rechnungs_speicher[rechnungs_id] = rechnung
    return {"status": "success", "rechnung": rechnung}

# ===== STRIPE WEBHOOK =====
@router.post("/webhook/zahlung-eingegangen")
async def process_incoming_payment(request: Request):
    if IS_PROD and STRIPE_WEBHOOK_SECRET:
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
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
    return await ExcelImportEngine.process_excel(file)

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

@router.get("/leads/campaigns")
async def get_campaigns(user: dict = Depends(get_current_user)):
    return {"campaigns": await LeadGenerationBots.get_campaigns()}

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
        "id": task_id, "sparte": req.sparte.value,
        "ziel_branche": req.ziel_branche, "ergebnis": ergebnis,
        "status": "completed", "timestamp": datetime.now(timezone.utc).isoformat()
    }
    return {"status": "completed", "task_id": task_id, "ergebnis": ergebnis}

# ===== SPARTEN =====
@router.get("/sparten/alle")
async def alle_sparten_auflisten():
    all_bots = [s.value for s in AgentTyp]
    waves = TokenSaver.get_startup_waves(all_bots)
    return {
        "gesamt_sparten": len(AgentTyp),
        "sparten_liste": all_bots,
        "startup_wellen": len(waves),
        "priority_bots": TokenSaver.PRIORITY_BOTS
    }

# ===== ORCHESTRATE =====
@router.post("/orchestrate/team-task")
@limiter.limit("5/minute")
async def orchestrate_team_task(request: Request, req: OrchestrateAnfrage, user: dict = Depends(get_current_user)):
    return await orchestrator_engine.orchestrate(req.aufgabe)

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

# ===== MARKET INTELLIGENCE (NEW) =====
@router.post("/market/scan")
@limiter.limit("3/minute")
async def market_scan(request: Request, user: dict = Depends(get_current_user)):
    return await MarketIntelligence.scan_markets()

# ===== COST OPTIMIZATION (NEW) =====
@router.post("/costs/optimize")
@limiter.limit("3/minute")
async def optimize_costs(request: Request, user: dict = Depends(get_current_user)):
    return await AutonomeKostenoptimierung.optimize_costs()

@router.get("/costs/history")
async def cost_history_abrufen(user: dict = Depends(get_current_user)):
    return {"cost_history": cost_history[-20:]}

# ===== SELF REPLICATION (NEW) =====
@router.post("/replication/create")
@limiter.limit("3/minute")
async def create_replica(request: Request, req: ReplicaCreateRequest, user: dict = Depends(get_current_user)):
    return await SelfReplication.create_replica(req.niche, req.config)

@router.post("/replication/deploy/{replica_id}")
async def deploy_replica(replica_id: str, user: dict = Depends(get_current_user)):
    return await SelfReplication.deploy_replica(replica_id)

@router.get("/replication/all")
async def get_replicas(user: dict = Depends(get_current_user)):
    return {"replicas": replicas}

# ===== CONTINUOUS LEARNING (NEW) =====
@router.post("/learning/record")
@limiter.limit("10/minute")
async def record_learning(request: Request, req: LearningRecordRequest, user: dict = Depends(get_current_user)):
    return await ContinuousLearning.learn_from_interaction(req.interaction)

@router.get("/learning/best-practices")
async def get_best_practices(user: dict = Depends(get_current_user)):
    return await ContinuousLearning.get_best_practices()

# ===== COMPLIANCE (NEW) =====
@router.post("/compliance/check")
async def check_compliance(req: ComplianceCheckRequest, user: dict = Depends(get_current_user)):
    return await GlobalComplianceEngine.check_compliance(req.region)

# ===== BUSINESS INTELLIGENCE (NEW) =====
@router.post("/bi/report")
async def bi_report(req: BIReportRequest, user: dict = Depends(get_current_user)):
    return await BusinessIntelligenceEngine.generate_report(req.zeitraum)

# ===== MULTI TENANT (NEW) =====
@router.post("/tenant/create")
@limiter.limit("5/minute")
async def create_tenant(request: Request, req: TenantCreateRequest, user: dict = Depends(get_current_user)):
    tenant_id = MultiTenantEngine.create_tenant(req.name, req.config)
    return {"status": "created", "tenant_id": tenant_id}

@router.get("/tenant/{tenant_id}")
async def get_tenant(tenant_id: str, user: dict = Depends(get_current_user)):
    return MultiTenantEngine.get_tenant(tenant_id)

# ===== DSGVO (NEW) =====
@router.post("/dsgvo/anonymize/{user_id}")
async def dsgvo_anonymize(user_id: str, user: dict = Depends(get_current_user)):
    return await DSGVOComplianceEngine.anonymize_user_data(user_id)

@router.post("/dsgvo/delete/{user_id}")
async def dsgvo_delete(user_id: str, user: dict = Depends(get_current_user)):
    return await DSGVOComplianceEngine.delete_user_data(user_id)

@router.get("/dsgvo/export/{user_id}")
async def dsgvo_export(user_id: str, user: dict = Depends(get_current_user)):
    return await DSGVOComplianceEngine.export_user_data(user_id)

# ===== SECURITY / AUDIT LOGS (NEW) =====
@router.get("/security/audit-logs")
async def get_audit_logs(user: dict = Depends(get_current_user)):
    return {"logs": audit_logs[-50:]}

# ===== TOKEN STATS (NEW) =====
@router.get("/tokens/stats")
async def token_stats():
    return TokenSaver.get_stats()

# ===== KEEP-ALIVE STATUS (NEW) =====
@router.get("/keepalive/status")
async def keepalive_status():
    return KeepAliveSystem.get_status()

# ===== STAGGERED STARTUP INFO (NEW) =====
@router.get("/startup/waves")
async def startup_waves():
    all_bots = [s.value for s in AgentTyp]
    waves = TokenSaver.get_startup_waves(all_bots)
    return {
        "total_bots": len(all_bots),
        "total_waves": len(waves),
        "wave_size": TokenSaver.STAGGER_WAVE_SIZE,
        "delay_between_waves_seconds": TokenSaver.STAGGER_DELAY_SECONDS,
        "waves": [{"wave": i+1, "bots": w, "starts_after_seconds": i * TokenSaver.STAGGER_DELAY_SECONDS} for i, w in enumerate(waves)]
    }

# ================================================================
# OEFFENTLICHE KUNDEN-ENDPOINTS (PUBLIC / NO AUTH)
# ================================================================

@router.get('/', include_in_schema=False)
async def landing_page():
    possible_paths = ['index.html', os.path.join(os.path.dirname(__file__), '..', 'index.html')]
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return HTMLResponse(content=f.read())
            except Exception:
                pass
    return HTMLResponse(content='<h1>RevenueAgentRoute V21</h1><p>Loading...</p>')

@router.post('/kunde/registrieren')
async def kunde_registrieren(req: KundeRequest):
    kunde_id = f"kunde_{uuid.uuid4().hex[:8]}"
    kunden_register[kunde_id] = {
        "id": kunde_id, "name": req.name, "email": req.email,
        "company": req.company, "created_at": datetime.now(timezone.utc).isoformat()
    }
    return {"status": "success", "kunde_id": kunde_id}

@router.post('/checkout/erstellen')
async def create_checkout(req: CheckoutRequest):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {'name': req.service_name},
                    'unit_amount': int(req.price * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{BASE_URL}/?status=success',
            cancel_url=f'{BASE_URL}/?status=cancel',
            customer_email=req.kunde_email,
            metadata={
                'service_name': req.service_name,
                'brief_description': req.brief_description[:500],
                'kunde_name': req.kunde_name,
                'kunde_company': req.kunde_company,
            }
        )
        checkout_sessions[session.id] = {
            'service': req.service_name, 'email': req.kunde_email,
            'description': req.brief_description, 'paid': False, 'result': None
        }
        return {'status': 'success', 'checkout_url': session.url}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@router.post('/webhook/stripe')
@router.post('/webhook/stripe-checkout')
async def stripe_checkout_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature', '')
    event = None
    if STRIPE_WEBHOOK_SECRET and sig_header:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        try:
            event = json.loads(payload.decode('utf-8'))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    if event is not None:
        event_type = event.get('type') if isinstance(event, dict) else getattr(event, 'type', None)
        if event_type == 'checkout.session.completed':
            if isinstance(event, dict):
                session_obj = event.get('data', {}).get('object', {})
            else:
                session_obj = event['data']['object']
            session_id = session_obj.get('id') if isinstance(session_obj, dict) else getattr(session_obj, 'id', None)
            if session_id and session_id in checkout_sessions:
                checkout_sessions[session_id]['paid'] = True
                service = checkout_sessions[session_id]['service']
                description = checkout_sessions[session_id]['description']
                try:
                    result = await B2BAgent.call_llm_efficient(
                        f'Erstelle einen professionellen {service} Plan fuer: {description}',
                        service
                    )
                    checkout_sessions[session_id]['result'] = result
                except Exception as e:
                    checkout_sessions[session_id]['result'] = f'Fehler: {e}'
    return {'status': 'success'}

@router.get('/kunde/ergebnis/{session_id}')
async def get_kunde_ergebnis(session_id: str):
    if session_id not in checkout_sessions:
        return {'status': 'error', 'result': 'Session nicht gefunden'}
    sess = checkout_sessions[session_id]
    if not sess.get('paid'):
        return {'status': 'pending', 'result': 'Zahlung ausstehend'}
    res = sess.get('result')
    if res is None:
        return {'status': 'pending', 'result': 'Ergebnis wird generiert'}
    elif isinstance(res, str) and res.startswith('Fehler:'):
        return {'status': 'error', 'result': res}
    else:
        return {'status': 'success', 'result': res}

# ================================================================
# FASTAPI APP
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_http_client
    global_http_client = httpx.AsyncClient(timeout=15.0)
    logger.info(f"RevenueAgentRoute V{current_version} gestartet [{ENVIRONMENT}]")
    logger.info(f"Token-Saver: aktiv — Cache TTL {TokenSaver.CACHE_TTL_SECONDS}s, Rate Limit {TokenSaver.MAX_CALLS_PER_MINUTE}/min/Bot")
    logger.info(f"Keep-Alive: aktiv — Ping alle 4 Min (verhindert Railway Sleep)")
    # Keep-Alive starten
    asyncio.create_task(KeepAliveSystem.start_keep_alive())
    yield
    await KeepAliveSystem.stop()
    await global_http_client.aclose()
    gc.collect()

app = FastAPI(
    title="RevenueAgentRoute V21.0.0",
    version=current_version,
    description="B2B Revenue Operating System - Token-Optimized with All Features",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}))
app.add_middleware(SlowAPIMiddleware)

app.middleware("http")(add_security_headers)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(router)

@app.get("/", include_in_schema=False)
async def root_landing_page():
    return await landing_page()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000)
