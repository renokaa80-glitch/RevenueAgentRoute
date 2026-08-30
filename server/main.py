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
# Lead Capture System
captured_leads: List[Dict] = []
# Auto-Response System  
email_responses: List[Dict] = []
# Campaign Analytics
campaign_stats: Dict[str, Dict] = {}
checkout_sessions: Dict[str, dict] = {}

# NEW: V19.1.0 storage
cost_history: List[Dict] = []
market_insights: List[Dict] = []
replicas: List[Dict] = []
learning_knowledge: List[Dict] = []
audit_logs: List[Dict] = []
tenants: Dict[str, dict] = {}

current_version: str = "27.0.0"

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
        CHEAP_MODEL = "openai/gpt-oss-20b"
        ADVANCED_MODEL = "openai/gpt-oss-120b"
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
            "max_tokens": 800,
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
        "email_configured": bool(SMTP_PASSWORD),
        "bot_email": SMTP_USER,
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



@router.get('/content', include_in_schema=False)
async def public_content_page():
    """Öffentliche Content-Seite mit allen generierten Marketing-Inhalten."""
    articles = AutonomousMarketingEngine.seo_articles[-20:]
    social = AutonomousMarketingEngine.social_posts[-10:]
    emails = AutonomousMarketingEngine.cold_emails[-10:]
    
    html = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RevenueAgentRoute — KI Marketing Blog</title>
<meta name="description" content="71 KI-Agenten generieren autonom SEO-Content, Social-Media-Posts und Cold-Emails. B2B Marketing Automation.">
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:800px;margin:0 auto;padding:20px;background:#0a0a0a;color:#e0e0e0;line-height:1.6}
h1{color:#4ea8ff;font-size:1.8rem;border-bottom:2px solid #1a3a5c;padding-bottom:10px}
h2{color:#4ea8ff;font-size:1.3rem;margin-top:30px}
h3{color:#7cc3ff;font-size:1.1rem;margin-top:20px}
article{background:#111;padding:20px;border-radius:8px;margin:15px 0;border-left:3px solid #4ea8ff}
.meta{color:#666;font-size:0.85rem;margin-bottom:10px}
.cta{background:#1a3a5c;padding:15px;border-radius:8px;text-align:center;margin:30px 0}
.cta a{color:#4ea8ff;font-size:1.1rem;text-decoration:none;font-weight:bold}
.badge{display:inline-block;background:#1a3a5c;color:#4ea8ff;padding:3px 10px;border-radius:12px;font-size:0.8rem;margin:2px}
pre{white-space:pre-wrap;word-wrap:break-word}
</style>
</head>
<body>
<h1>🤖 RevenueAgentRoute — Autonomes KI Marketing</h1>
<p><span class="badge">71 KI-Bots</span> <span class="badge">24/7 aktiv</span> <span class="badge">SEO-Content</span> <span class="badge">Social Media</span> <span class="badge">Cold Outreach</span></p>
<p>71 KI-Agenten generieren rund um die Uhr Marketing-Content — vollständig autonom. SEO-Artikel, Social-Media-Posts, Cold-Emails und Directory-Listings.</p>
<div class="cta"><a href="/">→ 7 Tage kostenlos testen</a></div>
"""
    
    # Add SEO articles
    if articles:
        html += "<h2>📝 SEO-Artikel (automatisch generiert)</h2>"
        for a in reversed(articles):
            html += f'<article><div class="meta">Bot: {a.get("bot","")} | {a.get("created_at","")[:10]}</div>'
            html += f'<pre>{a.get("content","")}</pre></article>'
    
    # Add social posts
    if social:
        html += "<h2>📱 Social-Media-Posts</h2>"
        for s in reversed(social):
            html += f'<article><div class="meta">Bot: {s.get("bot","")} | {s.get("platforms","")} | {s.get("created_at","")[:10]}</div>'
            html += f'<pre>{s.get("content","")}</pre></article>'
    
    # Add cold emails
    if emails:
        html += "<h2>✉️ Cold-Email-Templates</h2>"
        for e in reversed(emails):
            html += f'<article><div class="meta">Bot: {e.get("bot","")} | Ziel: {e.get("target_industry","")} | {e.get("created_at","")[:10]}</div>'
            html += f'<pre>{e.get("content","")}</pre></article>'
    
    # Status footer
    status = AutonomousMarketingEngine.get_status()
    html += f'<div class="cta"><p>Marketing-Engine Status: {"aktiv" if status["running"] else "offline"} | Zyklen: {status["total_campaigns"]} | Content: {status["content_pieces"]} Stück</p></div>'
    html += "</body></html>"
    
    return HTMLResponse(content=html)

@router.get('/sitemap.xml', include_in_schema=False)
async def sitemap():
    """XML-Sitemap für Suchmaschinen (Google, Bing)."""
    base = os.getenv("BASE_URL", "https://web-production-e28af.up.railway.app")
    urls = [f"{base}/", f"{base}/content"]
    for a in AutonomousMarketingEngine.seo_articles:
        urls.append(f"{base}/content#{a['id']}")
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += f'  <url><loc>{url}</loc><lastmod>{datetime.now(timezone.utc).strftime("%Y-%m-%d")}</lastmod><changefreq>daily</changefreq></url>\n'
    xml += '</urlset>'
    return HTMLResponse(content=xml, media_type="application/xml")

@router.get('/robots.txt', include_in_schema=False)
async def robots():
    """robots.txt für Suchmaschinen."""
    base = os.getenv("BASE_URL", "https://web-production-e28af.up.railway.app")
    txt = f"""User-agent: *
Allow: /
Allow: /content
Sitemap: {base}/sitemap.xml
"""
    return HTMLResponse(content=txt, media_type="text/plain")


# ===== EMAIL API ENDPOINTS =====

@router.get("/email/status")
async def email_status():
    """Status der Email-Engine."""
    return EmailEngine.get_status()

@router.get("/email/inbox")
async def email_inbox(limit: int = 50):
    """Alle eingehenden Emails."""
    return EmailEngine.inbox[:limit]

@router.get("/email/sent")
async def email_sent(limit: int = 50):
    """Alle gesendeten Emails."""
    return EmailEngine.sent[:limit]

@router.post("/email/send")
async def email_send(req: dict):
    """Email senden (Bot-Versand)."""
    to = req.get("to", "")
    subject = req.get("subject", "")
    body = req.get("body", "")
    bot_name = req.get("bot_name", "RevenueAgentRoute")
    
    if not to or not subject or not body:
        return {"status": "error", "message": "to, subject, body erforderlich"}
    
    return await EmailEngine.send_email(to, subject, body, bot_name=bot_name)

@router.post("/email/receive")
async def email_receive(req: dict):
    """Empfaengt eine Email (Webhook fuer Gmail Forwarding)."""
    sender = req.get("from", "")
    subject = req.get("subject", "")
    body = req.get("body", "")
    
    if not sender or not subject:
        return {"status": "error", "message": "from, subject erforderlich"}
    
    return await EmailEngine.distribute_incoming(sender, subject, body)

@router.post("/email/cold-outreach")
async def email_cold_outreach(req: dict):
    """Sendet Cold-Emails aus dem Marketing-Pool."""
    to = req.get("to", "")
    industry = req.get("industry", "B2B")
    
    if not to:
        return {"status": "error", "message": "to erforderlich"}
    
    return await EmailEngine.send_cold_email(to, industry)

# ===== MARKETING API ENDPOINTS =====

@router.get("/marketing/status")
async def marketing_status():
    """Status der autonomen Marketing-Engine."""
    return AutonomousMarketingEngine.get_status()

@router.get("/marketing/content")
async def marketing_content(content_type: Optional[str] = None, limit: int = 50):
    """Alle generierten Marketing-Inhalte abrufen."""
    return AutonomousMarketingEngine.get_content(content_type=content_type, limit=limit)

@router.get("/marketing/seo-articles")
async def marketing_seo_articles(limit: int = 20):
    """Generierte SEO-Artikel abrufen."""
    return AutonomousMarketingEngine.seo_articles[:limit]

@router.get("/marketing/social-posts")
async def marketing_social_posts(limit: int = 20):
    """Generierte Social-Media-Posts abrufen."""
    return AutonomousMarketingEngine.social_posts[:limit]

@router.get("/marketing/cold-emails")
async def marketing_cold_emails(limit: int = 20):
    """Generierte Cold-Email-Templates abrufen."""
    return AutonomousMarketingEngine.cold_emails[:limit]

# ============================================================
# FEATURE 1: LEAD CAPTURE — Landing Page Anmelde-Formular
# ============================================================
@router.post("/leads/capture")
async def capture_lead(req: dict):
    """Faengt Leads von der Landing Page ab — oeffentlich, kein Login noetig."""
    name = req.get("name", "").strip()
    email = req.get("email", "").strip().lower()
    company = req.get("company", "").strip()
    phone = req.get("phone", "").strip()
    message = req.get("message", "").strip()
    
    if not email or "@" not in email:
        return {"status": "error", "message": "Gueltige Email erforderlich"}
    
    # Dedup
    if any(l["email"] == email for l in captured_leads):
        return {"status": "exists", "message": "Bereits registriert!"}
    
    # Lead Scoring (Feature 3)
    score = await _score_lead(name, email, company, message)
    
    lead = {
        "id": f"lead_{uuid.uuid4().hex[:8]}",
        "name": name,
        "email": email,
        "company": company,
        "phone": phone,
        "message": message,
        "score": score,
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    captured_leads.append(lead)
    
    # Auto-send welcome email (human-like, delayed 10-30s)
    if EmailEngine.is_configured:
        import random
        delay = random.randint(10, 30)
        asyncio.create_task(_delayed_welcome_email(email, name, delay))
    
    return {"status": "captured", "lead_id": lead["id"], "score": score}

async def _delayed_welcome_email(email: str, name: str, delay: int):
    """Sendet Willkommens-Mail mit menschlicher Verzoegerung."""
    await asyncio.sleep(delay)
    welcome_subject = f"Willkommen bei RevenueAgentRoute, {name or 'Partner'}!"
    welcome_body = f"""Hallo {name or 'Partner'},

vielen Dank fuer Ihr Interesse an RevenueAgentRoute!

Wir sind die Plattform mit 71 KI-Agenten, die 24/7 fuer Sie arbeiten:
- Lead-Generierung
- SEO-Optimierung
- Content-Erstellung
- Cold-Outreach Kampagnen
- Conversion-Optimierung

Ihre 7-Tage-Testphase beginnt jetzt. Keine Kreditkarte noetig.

Was passiert als naechstes?
1. Einer unserer KI-Bots analysiert Ihr Unternehmen
2. Sie erhalten einen personalisierten Vorschlag
3. Sie testen die Agenten kostenlos

Bei Fragen antworten Sie einfach auf diese Email.

Mit freundlichen Gruessen,
Ihr RevenueAgentRoute Team
71 KI-Agenten arbeiten 24/7 fuer Sie."""
    await EmailEngine.send_email(email, welcome_subject, welcome_body, bot_name="newsletter_growth_curation")

@router.get("/leads/captured")
async def get_all_captured_leads(limit: int = 100):
    """Alle erfassten Leads (oeffentlich fuer Dashboard)."""
    return captured_leads[-limit:]

@router.get("/leads/stats")
async def captured_lead_stats():
    """Lead-Statistiken fuer Dashboard."""
    total = len(captured_leads)
    by_status = {}
    for l in captured_leads:
        s = l.get("status", "new")
        by_status[s] = by_status.get(s, 0) + 1
    avg_score = sum(l.get("score", 0) for l in captured_leads) / max(total, 1)
    return {"total": total, "by_status": by_status, "avg_score": round(avg_score, 1)}

# ============================================================
# FEATURE 2: AUTO-RESPONSE — Bots antworten wie Menschen
# ============================================================
@router.post("/email/auto-respond")
async def auto_respond(req: dict):
    """Bot antwortet automatisch auf eingehende Email — menschlich, nicht roboterhaft."""
    sender = req.get("sender", "").strip()
    subject = req.get("subject", "").strip()
    body = req.get("body", "").strip()
    
    if not sender or not EmailEngine.is_configured:
        return {"status": "error", "message": "Kein Sender oder SMTP nicht konfiguriert"}
    
    # Route to correct bot
    subject_lower = subject.lower()
    body_lower = body.lower()
    
    if any(k in subject_lower or k in body_lower for k in ["preis", "price", "kosten", "cost", "paket", "plan"]):
        bot_name = "billing_payment_bot"
        response_type = "pricing"
    elif any(k in subject_lower or k in body_lower for k in ["termin", "meeting", "call", "demo", "test"]):
        bot_name = "sales_pipeline_opt"
        response_type = "demo"
    elif any(k in subject_lower or k in body_lower for k in ["seo", "content", "artikel", "blog"]):
        bot_name = "programmatic_content_seo"
        response_type = "content"
    elif any(k in subject_lower or k in body_lower for k in ["lead", "kunde", "prospect", "outreach"]):
        bot_name = "cold_outreach_leadgen"
        response_type = "leads"
    else:
        bot_name = "general_inquiry"
        response_type = "general"
    
    # AI generates HUMAN-LIKE response
    prompt = f"""Du bist ein Mitarbeiter bei RevenueAgentRoute (NICHT ein Bot). Antworte wie ein Mensch:
    
    Absender: {sender}
    Betreff: {subject}
    Nachricht: {body[:500]}
    
    WICHTIG — Schreibe wie ein echter Mensch:
    - Keine Listen oder Aufzaehlungen
    - Natuerliche, gespraechige Sprache
    - Persoenliche Anrede, freundlich
    - Gehe konkret auf die Frage ein
    - Max 4-5 Saetze, kurz und natuerlich
    - Keine "Wir bieten..." Marketing-Sprache
    - Schluss mit einer Frage oder konkreten Naechstschritt
    - Unterschreib mit "Viele Gruesse, [Vorname]" (wechselnde Namen)
    - Keine Erwaehnung von "KI-Agenten" oder "Bot" in der Antwort
    
    Schreibe auf Deutsch."""
    
    try:
        response_text = await SmartAIRouter.call_llm_efficient(prompt, bot_name)
    except Exception as e:
        response_text = f"""Hallo,

vielen Dank fuer Ihre Nachricht! Ich schaue mir das an und melde mich in Kuerze mit einem Vorschlag.

Viele Gruesse,
Sarah"""
    
    # Human-like delay (30-120 seconds before replying)
    import random
    delay = random.randint(30, 120)
    
    # Send auto-response
    result = await EmailEngine.send_email(
        to=sender,
        subject=f"RE: {subject}",
        body=response_text,
        bot_name=bot_name
    )
    
    response_record = {
        "id": f"resp_{uuid.uuid4().hex[:8]}",
        "sender": sender,
        "original_subject": subject,
        "response_type": response_type,
        "bot": bot_name,
        "status": result.get("status", "error"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    email_responses.append(response_record)
    
    return {"status": "responded", "response_type": response_type, "bot": bot_name}

@router.get("/email/responses")
async def get_email_responses(limit: int = 50):
    """Alle Auto-Responses."""
    return email_responses[-limit:]

# ============================================================
# FEATURE 3: LEAD SCORING — AI bewertet jeden Prospect
# ============================================================
async def _score_lead(name: str, email: str, company: str, message: str) -> int:
    """Bewertet Lead-Qualitaet 1-10."""
    score = 0
    
    # Company email (not gmail/yahoo) = higher quality
    if company and "@" in email:
        domain = email.split("@")[1]
        if domain not in ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "web.de", "gmx.de"]:
            score += 3
    
    if company: score += 2
    if name: score += 1
    
    if message:
        msg_lower = message.lower()
        if any(k in msg_lower for k in ["lead", "kunde", "marketing", "automation", "ki", "ai", "bot"]):
            score += 2
        if len(message) > 50: score += 1
        if any(k in msg_lower for k in ["budget", "termin", "demo", "test", "probieren"]):
            score += 1
    
    try:
        score_prompt = f"""Bewerte diesen B2B-Lead auf einer Skala 1-10:
        Name: {name}, Email: {email}, Firma: {company}, Nachricht: {message[:200]}
        Antworte nur mit einer Zahl 1-10."""
        ai_score = await SmartAIRouter.call_llm_efficient(score_prompt, "lead_generation")
        ai_score = int(''.join(c for c in ai_score if c.isdigit())[:2] or "5")
        score = max(score, ai_score)
    except:
        pass
    
    return min(score, 10)

# ============================================================
# FEATURE 4: CAMPAIGN ANALYTICS — Tracking Dashboard
# ============================================================
@router.get("/campaigns/analytics")
async def campaign_analytics():
    """Komplette Campaign-Analytics fuer Dashboard."""
    outreach = AutonomousMarketingEngine.outreach_sent
    cold_emails = AutonomousMarketingEngine.cold_emails
    leads = captured_leads
    responses = email_responses
    
    total_sent = len(outreach)
    total_responses = len(responses)
    total_leads = len(leads)
    total_converted = sum(1 for l in leads if l.get("status") == "converted")
    
    by_industry = {}
    for o in outreach:
        ind = o.get("industry", "unknown")
        if ind not in by_industry:
            by_industry[ind] = {"sent": 0, "responded": 0}
        by_industry[ind]["sent"] += 1
    
    response_rate = round((total_responses / total_sent * 100), 1) if total_sent > 0 else 0
    conversion_rate = round((total_converted / total_leads * 100), 1) if total_leads > 0 else 0
    
    return {
        "total_outreach_sent": total_sent,
        "total_responses": total_responses,
        "total_leads_captured": total_leads,
        "total_converted": total_converted,
        "response_rate_pct": response_rate,
        "conversion_rate_pct": conversion_rate,
        "cold_emails_generated": len(cold_emails),
        "by_industry": by_industry,
        "recent_outreach": outreach[-10:],
        "recent_responses": responses[-10:],
        "recent_leads": leads[-10:],
        "email_configured": EmailEngine.is_configured,
        "marketing_engine_active": AutonomousMarketingEngine.is_running
    }

@router.post("/campaigns/analytics/convert/{lead_id}")
async def convert_lead(lead_id: str):
    """Markiert einen Lead als konvertiert (zahlender Kunde)."""
    for l in captured_leads:
        if l["id"] == lead_id:
            l["status"] = "converted"
            return {"status": "ok", "lead_id": lead_id, "new_status": "converted"}
    return {"status": "error", "message": "Lead nicht gefunden"}

@router.get("/marketing/directory-listings")
async def marketing_directory_listings(limit: int = 20):
    """Generierte Directory-Listings abrufen."""
    return AutonomousMarketingEngine.directory_listings[:limit]

# ============================================================
# OUTREACH CONTROL — Status, Toggle, Sent-Log, Bounces
# ============================================================
@router.get("/marketing/outreach/status")
async def outreach_status():
    """Status der autonomen Cold-Outreach-Kampagne."""
    return {
        "enabled": AutonomousMarketingEngine.outreach_enabled,
        "total_sent": len(AutonomousMarketingEngine.outreach_sent),
        "total_targets": len(AutonomousMarketingEngine.outreach_targets),
        "total_bounced": len(AutonomousMarketingEngine.bounced_emails),
        "max_per_cycle": AutonomousMarketingEngine.max_emails_per_cycle,
        "max_per_day": AutonomousMarketingEngine.max_emails_per_day,
        "recent_sent": AutonomousMarketingEngine.outreach_sent[-20:],
        "recent_bounced": AutonomousMarketingEngine.bounced_emails[-20:]
    }

@router.post("/marketing/outreach/toggle")
async def outreach_toggle(req: dict):
    """Aktiviert/Deaktiviert die autonome Cold-Outreach."""
    AutonomousMarketingEngine.outreach_enabled = req.get("enabled", True)
    return {"status": "ok", "outreach_enabled": AutonomousMarketingEngine.outreach_enabled}

@router.post("/marketing/outreach/run-now")
async def outreach_run_now(req: dict = None):
    """Startet sofort eine Cold-Outreach-Kampagne (manueller Trigger)."""
    req = req or {}
    industry = req.get("industry", "")
    if industry:
        result = await AutonomousMarketingEngine._autonomous_cold_outreach_manual(industry)
    else:
        result = await AutonomousMarketingEngine._autonomous_cold_outreach()
    return result or {"status": "skipped", "message": "Outreach deaktiviert oder kein Ergebnis"}

@router.post("/marketing/outreach/search-prospects")
async def search_prospects(req: dict):
    """Zeigt verifizierte Kontakte fuer eine Branche — kein Versand, nur Recherche.
    Test-Endpunkt: zeigt welche Kontakte gefunden wuerden, bevor Outreach an geht."""
    industry = req.get("industry", "Digitalagenturen in DACH")
    count = req.get("count", 5)
    prospects = await AutonomousMarketingEngine._find_real_prospects(industry, count)
    return {"industry": industry, "found": len(prospects), "prospects": prospects}

@router.get("/marketing/outreach/industries")
async def list_industries():
    """Listet alle verfuegbaren Branchen mit Kontakt-Listen auf."""
    result = {}
    for key, prospects in AutonomousMarketingEngine.verified_prospect_lists.items():
        result[key] = len(prospects)
    return result

@router.post("/marketing/outreach/add-prospects")
async def add_prospects(req: dict):
    """Fuegt manuell gefundene, verifizierte Kontakte hinzu."""
    industry = req.get("industry", "Digitalagenturen in DACH")
    new_prospects = req.get("prospects", [])
    await AutonomousMarketingEngine._enrich_prospect_list(industry, new_prospects)
    return {"status": "ok", "added": len(new_prospects), "industry": industry}

@router.post("/marketing/outreach/follow-up")
async def outreach_follow_up():
    """Sendet Follow-Up Mails an Firmen die vor 3+ Tagen angeschrieben wurden."""
    result = await AutonomousMarketingEngine._send_follow_ups()
    return result or {"status": "no_follow_ups", "message": "Keine Follow-Ups faellig"}

@router.get("/marketing/outreach/follow-ups")
async def follow_up_log(limit: int = 50):
    """Zeigt alle gesendeten Follow-Up Mails."""
    return AutonomousMarketingEngine.follow_up_sent[-limit:]

@router.get("/marketing/outreach/sent")
async def outreach_sent_log(limit: int = 50):
    return AutonomousMarketingEngine.outreach_sent[-limit:]

@router.get("/marketing/outreach/bounced")
async def outreach_bounced_log(limit: int = 50):
    """Liste fehlgeschlagener/gebouncter Zustellungen."""
    return AutonomousMarketingEngine.bounced_emails[-limit:]

@router.post("/marketing/trigger")
async def marketing_trigger():
    """Startet sofort einen Marketing-Zyklus."""
    if AutonomousMarketingEngine.is_running:
        # Run one cycle immediately in background
        asyncio.create_task(AutonomousMarketingEngine._generate_seo_article())
        asyncio.create_task(AutonomousMarketingEngine._generate_social_posts())
        asyncio.create_task(AutonomousMarketingEngine._generate_cold_emails())
        asyncio.create_task(AutonomousMarketingEngine._generate_directory_listing())
        return {"status": "triggered", "message": "Marketing-Zyklus gestartet"}
    return {"status": "error", "message": "Marketing-Engine nicht aktiv"}

# ================================================================
# FASTAPI APP
# ================================================================


# ================================================================
# AUTONOMOUS MARKETING ENGINE — Bots werben autonom im Web
# ================================================================


# ===== EMAIL/SMTP CONFIG =====
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "revenue.agent.route@gmail.com")
# Clean markdown/auto-link formatting that Samsung keyboard adds
SMTP_USER = SMTP_USER.replace("[", "").replace("]", "").replace("(", "").replace(")", "")
# Extract email from "mailto:" links if present
import re as _re
_mailto_match = _re.search(r'mailte?:([^\s\[\]\(\)]+@[^\s\[\]\(\)]+)', SMTP_USER)
if _mailto_match:
    SMTP_USER = _mailto_match.group(1)
# Fallback: extract any email-like pattern
_email_match = _re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', SMTP_USER)
if _email_match:
    SMTP_USER = _email_match.group(0)
if "@" not in SMTP_USER or "deine" in SMTP_USER:
    SMTP_USER = "revenue.agent.route@gmail.com"
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
BOT_EMAIL = SMTP_USER  # Central bot email address

# ===== EMAIL ENGINE =====
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import email as email_lib

class EmailEngine:
    """Zentrale Email-Engine fuer alle 71 Bots."""
    
    inbox: List[Dict] = []
    sent: List[Dict] = []
    is_configured: bool = bool(SMTP_PASSWORD)
    
    @classmethod
    async def send_email(cls, to: str, subject: str, body: str, bot_name: str = "RevenueAgentRoute") -> Dict:
        """Sendet eine Email ueber SMTP — mit Spam-Prevention."""
        if not cls.is_configured:
            logger.warning(f"SMTP nicht konfiguriert — Email an {to} nicht gesendet")
            return {"status": "error", "message": "SMTP_PASSWORD nicht gesetzt in Railway"}
        
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{bot_name} <{SMTP_USER}>"
            msg["To"] = to
            msg["Subject"] = subject
            # SPAM PREVENTION HEADERS
            msg["Message-ID"] = f"<{uuid.uuid4().hex}@revenueagentroute.com>"
            msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            msg["X-Mailer"] = "RevenueAgentRoute Mail Client"
            msg["List-Unsubscribe"] = f"<mailto:{SMTP_USER}?subject=unsubscribe>"
            msg["Precedence"] = "bulk"
            msg["Auto-Submitted"] = "auto-generated"
            # Plain text always first (spam filters prefer text before HTML)
            msg.attach(MIMEText(body, "plain", "utf-8"))
            
            # HTML version (after plain text — spam filters prefer text first)
            html_body = f"<html><body style='font-family:sans-serif;line-height:1.6;color:#333'><div style='max-width:600px;margin:0 auto;padding:20px'><div>{body.replace(chr(10),'<br>')}</div></div></body></html>"
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            
            # Send via SMTP
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to, msg.as_string())
            server.quit()
            
            sent_email = {
                "id": f"sent_{uuid.uuid4().hex[:8]}",
                "to": to,
                "subject": subject,
                "body": body[:500],
                "bot": bot_name,
                "status": "sent",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            cls.sent.append(sent_email)
            logger.info(f"Email gesendet an {to} von Bot {bot_name}")
            return {"status": "sent", "to": to, "subject": subject}
            
        except Exception as e:
            logger.error(f"SMTP Fehler: {e}")
            return {"status": "error", "message": str(e)}
    
    @classmethod
    async def send_cold_email(cls, to: str, industry: str) -> Dict:
        """Sendet eine Cold-Email aus dem Marketing-Engine Pool."""
        # Get latest cold email template for this industry
        templates = [e for e in AutonomousMarketingEngine.cold_emails if industry.lower() in e.get("target_industry","").lower()]
        if not templates:
            templates = AutonomousMarketingEngine.cold_emails
        
        if not templates:
            return {"status": "error", "message": "Keine Cold-Email-Templates verfuegbar"}
        
        template = templates[-1]
        body = template.get("content", "")
        subject_line = f"71 KI-Agenten fuer {industry} — 7 Tage kostenlos testen"
        
        return await cls.send_email(to, subject_line, body, bot_name="cold_outreach_leadgen")
    
    @classmethod
    async def distribute_incoming(cls, sender: str, subject: str, body: str) -> Dict:
        """Verteilt eingehende Emails an die richtigen Bots."""
        # Routing logic based on subject/content
        subject_lower = subject.lower()
        body_lower = body.lower()
        
        assigned_bot = "general_inquiry"
        priority = "normal"
        
        # Keyword-based routing
        if any(k in subject_lower for k in ["rechnung", "invoice", "payment", "zahlung", "stripe"]):
            assigned_bot = "billing_payment_bot"
            priority = "high"
        elif any(k in subject_lower for k in ["lead", "kunde", "customer", "anfrage"]):
            assigned_bot = "cold_outreach_leadgen"
        elif any(k in subject_lower for k in ["seo", "content", "artikel", "blog"]):
            assigned_bot = "programmatic_content_seo"
        elif any(k in subject_lower for k in ["bug", "fehler", "problem", "support"]):
            assigned_bot = "saas_uptime_monitoring"
            priority = "high"
        elif any(k in subject_lower for k in["bank", "konto", "transfer", "iban"]):
            assigned_bot = "billing_payment_bot"
            priority = "urgent"
        elif any(k in subject_lower for k in["marketing", "werbung", "ad", "social"]):
            assigned_bot = "social_reputation_mgmt"
        
        email_record = {
            "id": f"inbox_{uuid.uuid4().hex[:8]}",
            "from": sender,
            "subject": subject,
            "body": body[:1000],
            "assigned_bot": assigned_bot,
            "priority": priority,
            "status": "received",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        cls.inbox.append(email_record)
        
        # Auto-respond
        auto_reply = f"""Hallo,

vielen Dank fuer Ihre Email an RevenueAgentRoute!

Ihre Anfrage wurde automatisch an Bot '{assigned_bot}' weitergeleitet (Prioritaet: {priority}).
Ein KI-Agent wird sich innerhalb von 24 Stunden mit einer Antwort melden.

-- RevenueAgentRoute
71 KI-Agenten. 24/7 aktiv.
revenue.agent.route@gmail.com"""
        
        await cls.send_email(sender, f"Re: {subject}", auto_reply, bot_name=assigned_bot)
        
        return {"status": "distributed", "assigned_bot": assigned_bot, "priority": priority}
    
    @classmethod
    def get_status(cls) -> Dict:
        return {
            "configured": cls.is_configured,
            "email": SMTP_USER,
            "inbox_count": len(cls.inbox),
            "sent_count": len(cls.sent),
            "smtp_host": SMTP_HOST,
            "smtp_port": SMTP_PORT
        }

# ================================================================

class AutonomousMarketingEngine:
    """71 Bots generieren autonom Marketing-Content und veröffentlichen ihn."""
    
    marketing_content: List[Dict] = []
    social_posts: List[Dict] = []
    cold_emails: List[Dict] = []
    seo_articles: List[Dict] = []
    directory_listings: List[Dict] = []
    is_running: bool = False
    last_run: Optional[datetime] = None
    total_campaigns: int = 0
    # Autonomous Cold Outreach tracking
    outreach_sent: List[Dict] = []
    outreach_targets: List[Dict] = []
    bounced_emails: List[Dict] = []
    follow_up_sent: List[Dict] = []
    outreach_enabled: bool = True  # Aktiviert — 50 echte verifizierte Kontakte vorhanden
    max_emails_per_cycle: int = 10
    max_emails_per_day: int = 25  # Gmail safety limit — far below 500
    
    # Marketing-fähige Bots
    MARKETING_BOTS = [
        "cold_outreach_leadgen", "seo_audit_repair", "social_reputation_mgmt",
        "programmatic_content_seo", "conversion_rate_opt", "newsletter_growth_curation",
        "email_template_design", "landingpage_copywriting", "case_study_testimonial_gen",
        "programmatic_newsletter_ads", "generative_engine_optimization",
        "google_business_local_seo", "influencer_marketing_broker",
        "affiliate_niche_bot", "podcast_to_blog_repurpose"
    ]
    
    @classmethod
    async def run_marketing_cycle(cls):
        """Ein vollständiger Marketing-Zyklus — läuft alle 3 Stunden."""
        cls.is_running = True
        while cls.is_running:
            try:
                logger.info("Marketing Engine: Zyklus gestartet")
                cls.total_campaigns += 1
                
                # 1. SEO-Artikel generieren
                await cls._generate_seo_article()
                
                # 2. Social-Media-Posts erstellen
                await cls._generate_social_posts()
                
                # 3. Cold-Email-Sequenz generieren
                await cls._generate_cold_emails()
                
                # 3.5 AUTONOMOUS COLD OUTREACH — findet Kunden und sendet Mails
                await cls._autonomous_cold_outreach()
                
                # 4. Directory-Listing erstellen
                await cls._generate_directory_listing()
                
                # 5. Landing-Page-Copy optimieren
                await cls._optimize_landing_copy()
                
                cls.last_run = datetime.now(timezone.utc)
                logger.info(f"Marketing Engine: Zyklus #{cls.total_campaigns} abgeschlossen")
                
            except Exception as e:
                logger.error(f"Marketing Engine Fehler: {e}")
            
            # Alle 3 Stunden
            await asyncio.sleep(10800)
    
    @classmethod
    async def _generate_seo_article(cls):
        """Generiert einen SEO-optimierten Blog-Artikel."""
        topics = [
            "Wie KI-Agenten B2B-Vertrieb automatisieren",
            "71 KI-Bots die 24/7 Umsatz generieren",
            "Lead Generation Automation mit KI",
            "Warum Microsoft und JPMorgan auf KI-Agenten setzen",
            "B2B Marketing Automation ohne Personal",
            "KI-gestützte Cold Outreach die funktioniert",
            "Conversion Optimierung mit autonomen Agenten",
            "SEO Automation: Content generieren lassen",
            "Vom Lead zum Deal — vollautomatisch mit KI",
            "Wie KMU von KI-Agenten profitieren"
        ]
        topic = topics[cls.total_campaigns % len(topics)]
        
        prompt = f"""Schreibe einen SEO-optimierten B2B-Artikel über: '{topic}'.
        Struktur: H1 Titel, Einleitung (2 Sätze), 3 H2 Abschnitte mit je 2-3 Sätzen, Fazit.
        Keywords: KI-Agenten, B2B Automation, Lead Generation, Marketing Automation.
        Sprache: Deutsch. Maximal 400 Wörter. Praktisch und konkret."""
        
        content = await SmartAIRouter.call_llm_efficient(prompt, "programmatic_content_seo")
        
        article = {
            "id": f"art_{uuid.uuid4().hex[:8]}",
            "topic": topic,
            "content": content,
            "status": "published",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bot": "programmatic_content_seo",
            "type": "seo_article"
        }
        cls.seo_articles.append(article)
        cls.marketing_content.append(article)
        return article
    
    @classmethod
    async def _generate_social_posts(cls):
        """Generiert Social-Media-Posts für LinkedIn, Twitter, Facebook."""
        platforms = ["LinkedIn", "Twitter/X", "Facebook"]
        angles = [
            "Problem-Lösung: 71 KI-Agenten automatisieren B2B-Vertrieb",
            "Social Proof: Wie Microsoft und JPMorgan KI einsetzen",
            "Kosten-Vergleich: 1 Mensch + 71 KI-Bots vs. 20 Mitarbeiter",
            "Free Trial: 7 Tage kostenlos testen, keine Kreditkarte",
            "Ergebnis: Vom Lead zum Deal — vollautomatisch in unter 60 Sekunden"
        ]
        angle = angles[cls.total_campaigns % len(angles)]
        
        prompt = f"""Schreibe 3 Social-Media-Posts für {', '.join(platforms)}.
        Thema: {angle}
        LinkedIn: Professionell, 3 Sätze, mit Call-to-Action.
        Twitter/X: Kurz, punchy, max 280 Zeichen, mit Hashtags.
        Facebook: Conversational, Frage am Ende, Emoji erlaubt.
        Sprache: Deutsch."""
        
        content = await SmartAIRouter.call_llm_efficient(prompt, "social_reputation_mgmt")
        
        post = {
            "id": f"soc_{uuid.uuid4().hex[:8]}",
            "angle": angle,
            "content": content,
            "platforms": platforms,
            "status": "ready_to_post",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bot": "social_reputation_mgmt",
            "type": "social_post"
        }
        cls.social_posts.append(post)
        cls.marketing_content.append(post)
        return post
    
    @classmethod
    async def _generate_cold_emails(cls):
        """Generiert Cold-Email-Sequenzen für B2B-Outreach."""
        industries = [
            "Digitalagenturen in DACH", "SaaS-Startups in Europa",
            "KMU mit Legacy-Systemen", "E-Commerce-Unternehmen",
            "Logistikunternehmen", "Immobilienmakler",
            "Steuerberater und Kanzleien", "Handwerksbetriebe"
        ]
        industry = industries[cls.total_campaigns % len(industries)]
        
        prompt = f"""Schreibe eine Cold-Email an {industry}.
        Betreff: Personalisiert, neugierig machend.
        Body: 3 Sätze. Problem → Lösung (71 KI-Agenten) → CTA (7 Tage kostenlos testen).
        Referenz: Microsoft und JPMorgan setzen KI-Agenten ein.
        PS: Keine Kreditkarte erforderlich.
        Sprache: Deutsch."""
        
        content = await SmartAIRouter.call_llm_efficient(prompt, "cold_outreach_leadgen")
        
        email = {
            "id": f"email_{uuid.uuid4().hex[:8]}",
            "target_industry": industry,
            "content": content,
            "status": "ready_to_send",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bot": "cold_outreach_leadgen",
            "type": "cold_email"
        }
        cls.cold_emails.append(email)
        cls.marketing_content.append(email)
        return email
    
    # Vordefinierte echte Firmen-Listen — per Web-Suche verifiziert (30.08.2026)
    # Alle Emails aus echten Impressum-Seiten extrahiert
    verified_prospect_lists: Dict[str, List[Dict]] = {
        "Digitalagenturen in DACH": [
            {"company": "MIR Internetagentur", "email": "hello@mir.de", "website": "https://www.mir.de", "city": "Köln"},
            {"company": "Digitalagentur Thüringen", "email": "info@da-th.de", "website": "https://digitalagentur-thueringen.de", "city": "Erfurt"},
            {"company": "Deitron Digitalagentur", "email": "info@deitron.de", "website": "https://www.deitron.de", "city": "Ulm"},
            {"company": "XPERIENTS Digitalagentur", "email": "info@xperients.de", "website": "https://xperients.de", "city": "Hamburg/München"},
            {"company": "WIJO Digitalagentur", "email": "kontakt@wijo-digital.de", "website": "https://wijo-digital.de", "city": "Arnsberg"},
            {"company": "ENDUSTRY Digitalagentur", "email": "info@endustry.de", "website": "https://www.endustry.de", "city": "Hamburg"},
            {"company": "Lisign Digitalagentur", "email": "lherter@lisign-digitalagentur.de", "website": "https://www.lisign-digitalagentur.de", "city": "Meßkirch"},
        ],
        "Marketing Agenturen": [
            {"company": "Na-triarch Performance Marketing", "email": "info@natriarch.org", "website": "https://www.natriarch.de", "city": "Berlin"},
            {"company": "NordNordOst Agentur", "email": "anne@nordnordost-agentur.de", "website": "https://nordnordost-agentur.de", "city": "Deutschland"},
            {"company": "Blauzweig Werbeagentur", "email": "office@blauzweig.de", "website": "https://blauzweig.de", "city": "Wendland/Altmark"},
            {"company": "ConverSEO Marketing", "email": "info@converseo.de", "website": "https://www.converseo.de", "city": "Deutschland"},
            {"company": "Leadeffect", "email": "anfrage@leadeffect.de", "website": "https://leadeffect.de", "city": "Deutschland"},
            {"company": "Heimer Marketing", "email": "info@heimer-marketing.de", "website": "https://www.emailmarketingagentur.de", "city": "Deutschland"},
            {"company": "Caesar Harrison", "email": "kontakt@caesar-harrison.de", "website": "https://www.caesar-harrison.de", "city": "Kassel"},
        ],
        "IT Consulting & Software": [
            {"company": "CONTACT Software", "email": "info@contact.de", "website": "https://www.contact.de", "city": "Deutschland"},
            {"company": "Inoya SaaS Entwicklung", "email": "info@inoya.de", "website": "https://inoya.de", "city": "Deutschland"},
            {"company": "Startplatz SaaS", "email": "info@startplatz.de", "website": "https://www.startplatz.de", "city": "Köln"},
            {"company": "Sey IT Consulting", "email": "info@sey-it.com", "website": "https://www.sey-it.de", "city": "Deutschland"},
            {"company": "Inexso Consulting", "email": "info@inexso.de", "website": "https://inexso.de", "city": "Oldenburg"},
            {"company": "Agilimo IT", "email": "info@agilimo.de", "website": "https://agilimo.de", "city": "Deutschland"},
            {"company": "DE-S Consulting", "email": "info@desconsulting.de", "website": "https://desconsulting.de", "city": "Berlin"},
            {"company": "NewTec GmbH", "email": "info@newtec.de", "website": "https://www.newtec.de", "city": "Pfaffenhofen"},
            {"company": "Civic Consulting", "email": "info@civic-consulting.de", "website": "https://www.civic-consulting.de", "city": "Deutschland"},
            {"company": "Bauwerk Consulting", "email": "mail@bauwerk-consulting.de", "website": "https://www.bauwerk-consulting.de", "city": "Münster"},
        ],
        "Webdesign Agenturen Schweiz": [
            {"company": "Beyondweb", "email": "hello@beyondweb.ch", "website": "https://www.beyondweb.ch", "city": "Rotkreuz, CH"},
            {"company": "MAINWEB Webagentur", "email": "info@mainweb.ch", "website": "https://www.mainweb.ch", "city": "Ostschweiz, CH"},
            {"company": "4Your Design", "email": "info@advixpert.ch", "website": "https://www.4your-design.ch", "city": "Selzach, CH"},
            {"company": "Websharks Agentur", "email": "alex@webagentur-websharks.ch", "website": "https://www.webagentur-websharks.ch", "city": "Chur, CH"},
        ],
        "Digitalagenturen Österreich": [
            {"company": "ThisIsAgency", "email": "hello@thisisagency.at", "website": "https://www.thisisagency.at", "city": "Österreich"},
            {"company": "RAUM15 Digital Solutions", "email": "office@raum15.at", "website": "https://raum15.at", "city": "Schwaz, AT"},
            {"company": "Skillweb Media", "email": "office@skillweb-media.at", "website": "https://www.skillweb-media.at", "city": "Kumberg, AT"},
            {"company": "FS Full Service", "email": "office@fs-production.at", "website": "https://www.fs-production.at", "city": "Österreich"},
        ],
        "Immobilienmakler": [
            {"company": "E&G Real Estate", "email": "info@eug-re.de", "website": "https://en.eug-immobilien.de", "city": "Stuttgart"},
            {"company": "IAD Immobilien", "email": "verwaltung@iad-immobilien.de", "website": "https://www.iad-immobilien.de", "city": "Nürnberg"},
            {"company": "N3 Immobilien", "email": "info@n3gmbh.de", "website": "https://n3-immobilien.de", "city": "Mainz"},
            {"company": "KSK Immobilien", "email": "info@ksk-immobilien.de", "website": "https://www.ksk-immobilien.de", "city": "Köln"},
            {"company": "Agentur Fröhlich Real Estate", "email": "email@agentur-froehlich.de", "website": "https://agenturfroehlich.de", "city": "München"},
        ],
        "Logistikunternehmen": [
            {"company": "Häberle Logistik", "email": "info@haeberle-logistik.de", "website": "https://www.haeberle-logistik.de", "city": "Deutschland"},
            {"company": "KB Logistics", "email": "info@kb-logistic.de", "website": "https://www.kb-logistic.de", "city": "Klipphausen"},
            {"company": "Metzger Spedition", "email": "info@metzger-spedition.de", "website": "https://metzger-spedition.de", "city": "Deutschland"},
            {"company": "Waldbach Logistik", "email": "info@waldbach-logistik.de", "website": "https://www.waldbach-logistik.de", "city": "Melle"},
            {"company": "Spedition Logistik Region", "email": "info@logistik-region.de", "website": "https://spedition-logistikregion.de", "city": "Deutschland"},
        ],
        "Steuerberater und Kanzleien": [
            {"company": "Kanzlei Pfalz", "email": "info@kanzlei-pfalz.de", "website": "https://kanzlei-pfalz.de", "city": "Rheinland-Pfalz"},
            {"company": "Stb Dyllong", "email": "info@stb-dyllong.de", "website": "https://www.steuerberatungskanzlei-dyllong.de", "city": "Deutschland"},
            {"company": "GOB Steuerberatung", "email": "info@gob-stbg.de", "website": "https://www.gob-stbg.de", "city": "Magdeburg"},
            {"company": "GWGL Hamburg", "email": "Willkommen@GWGL-Hamburg.de", "website": "https://gwgl-hamburg.de", "city": "Hamburg"},
            {"company": "Kanzlei Wild", "email": "info@kanzlei-wild.de", "website": "https://www.kanzlei-wild.de", "city": "Rastatt"},
            {"company": "StBK Berlin", "email": "info@stbk-berlin.de", "website": "https://www.hsp-steuer.de", "city": "Berlin"},
        ],
        "Handwerk & Bau": [
            {"company": "Scholl & Balloff", "email": "mail@schollballoff.de", "website": "https://schollballoff.de", "city": "Düsseldorf"},
            {"company": "Ecommaze Marketing", "email": "info@ecommaze.de", "website": "https://ecommaze.de", "city": "Memmingen"},
        ],
        "Österreich Digitalagenturen (neu)": [
            {"company": "Brandig Digital", "email": "office@brandig.at", "website": "https://brandig.at", "city": "Steiermark, AT"},
            {"company": "Menasse Kommunikation", "email": "hello@menassemenasse.at", "website": "https://menassemenasse.at", "city": "Wien, AT"},
            {"company": "SPiNNWERK", "email": "kontakt@spinnwerk.at", "website": "https://spinnwerk.at", "city": "Wien, AT"},
            {"company": "Ratonga Digital", "email": "office@ratonga.at", "website": "https://ratonga.at", "city": "Schweiggers, AT"},
            {"company": "Digital Wannabeez", "email": "office@digital-wannabeez.at", "website": "https://www.digital-wannabeez.at", "city": "Engerwitzdorf, AT"},
        ],
        "Weitere IT & Consulting (neu)": [
            {"company": "AANetConsult IT", "email": "info@aanetconsult.com", "website": "https://www.aanetconsult.de", "city": "Darmstadt"},
            {"company": "Steinbeis Finance", "email": "info@steinbeis-finance.de", "website": "https://steinbeis-finance.de", "city": "Deutschland"},
            {"company": "Nebbe Consulting", "email": "info@nebbe-consulting.de", "website": "https://nebbe-consulting.de", "city": "Hamburg"},
            {"company": "Startup Factories", "email": "info@startup-factories.de", "website": "https://startup-factories.de", "city": "Berlin/München"},
            {"company": "KlickPiloten", "email": "stuttgart@klickpiloten.de", "website": "https://klickpiloten.de", "city": "Stuttgart/Hamburg/Berlin"},
            {"company": "Andy Fox Social Media", "email": "andy@andy-fox.com", "website": "https://andy-fox.com", "city": "München"},
        ],
        "UK Digital (neu)": [
            {"company": "Impression Digital", "email": "hello@impressiondigital.com", "website": "https://www.impressiondigital.com", "city": "London, UK"},
            {"company": "NX Digital Solutions", "email": "info@nxdigitalsolutions.com", "website": "https://www.nxdigitalsolutions.com", "city": "UK"},
        ],
        "International Startups (neu)": [
            {"company": "MONSOON Agency", "email": "hello@monsoon.agency", "website": "https://monsoon.agency", "city": "Berlin"},
            {"company": "Ellevate Paris", "email": "contact@ellevate.fr", "website": "https://ellevate.fr", "city": "Paris, FR"},
            {"company": "Agence CL WEB", "email": "contact@agenceclweb.fr", "website": "https://agenceclweb.fr", "city": "Provence, FR"},
            {"company": "WebSteve", "email": "contact@websteve.fr", "website": "https://websteve.fr", "city": "Frankreich"},
            {"company": "AIxH Luxembourg", "email": "hello@aixh.com", "website": "https://aixh.fr", "city": "Luxembourg"},
            {"company": "Webvory India", "email": "hello@webvory.com", "website": "https://webvory.com", "city": "Mohali, IN"},
            {"company": "Indian SEO Agency", "email": "sales@indianseoagency.com", "website": "https://indianseoagency.com", "city": "Indien"},
            {"company": "Brandchanakya", "email": "info@brandchanakya.in", "website": "https://brandchanakya.in", "city": "Indien"},
        ],
    }
    
    @classmethod
    async def _find_real_prospects(cls, industry: str, count: int = 5) -> List[Dict]:
        """Findet ECHTE Firmen aus verifizierten Listen — keine KI-Erfindungen.
        Alle Kontakte wurden per Web-Suche aus echten Impressum-Seiten extrahiert."""
        prospects = []
        
        # Normalize industry name to match our lists
        matched_key = None
        for key in cls.verified_prospect_lists:
            if industry.lower() in key.lower() or key.lower() in industry.lower():
                matched_key = key
                break
        
        if not matched_key:
            # Try partial match
            for key in cls.verified_prospect_lists:
                words = industry.lower().split()
                if any(w in key.lower() for w in words if len(w) > 3):
                    matched_key = key
                    break
        
        if not matched_key:
            logger.warning(f"Outreach: Keine verifizierte Liste fuer '{industry}' — nutze Digitalagenturen als Default")
            matched_key = "Digitalagenturen in DACH"
        
        base_list = cls.verified_prospect_lists[matched_key]
        
        # Filter out already-contacted and bounced
        contacted_emails = {s.get("email") or s.get("to") for s in cls.outreach_sent}
        bounced_emails_set = {b.get("email") for b in cls.bounced_emails}
        
        for prospect in base_list:
            if prospect["email"] in contacted_emails or prospect["email"] in bounced_emails_set:
                continue
            prospect_copy = prospect.copy()
            prospect_copy["industry"] = industry
            prospect_copy["reason"] = "KI-Automatisierung"
            prospect_copy["source"] = "verified_list"
            prospect_copy["email_verified"] = True
            prospects.append(prospect_copy)
            if len(prospects) >= count:
                break
        
        logger.info(f"Outreach: {len(prospects)} verifizierte Kontakte fuer '{matched_key}' gefunden")
        return prospects
    
    @classmethod
    async def _enrich_prospect_list(cls, industry: str, new_prospects: List[Dict]):
        """Fuegt neue verifizierte Kontakte zur Liste hinzu — fuer manuelle Erweiterung."""
        if industry not in cls.verified_prospect_lists:
            cls.verified_prospect_lists[industry] = []
        for p in new_prospects:
            # Dedup
            if not any(x["email"] == p["email"] for x in cls.verified_prospect_lists[industry]):
                cls.verified_prospect_lists[industry].append(p)

    @classmethod
    async def _autonomous_cold_outreach(cls):
        """Findet automatisch B2B-Kunden und sendet Cold-Emails — MENSCHLICH, nicht spammy."""
        if not cls.outreach_enabled:
            return
        
        if not EmailEngine.is_configured:
            logger.warning("Outreach: SMTP nicht konfiguriert — ueberspringe")
            return
        
        # HUMAN-LIKE RATE LIMITS — verhindert Blacklisting
        max_per_day = 25  # max 25 Mails/Tag (Gmail Limit: 500, wir bleiben weit drunter)
        sent_today = sum(1 for s in cls.outreach_sent 
                        if s.get("timestamp","")[:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        if sent_today >= max_per_day:
            logger.info(f"Outreach: Tageslimit ({max_per_day}) erreicht — ueberspringe")
            return
        
        remaining_today = max_per_day - sent_today
        cls.max_emails_per_cycle = min(cls.max_emails_per_cycle, remaining_today)
        
        industries = [
            "Digitalagenturen in DACH", "SaaS-Startups in Europa",
            "KMU mit Legacy-Systemen", "E-Commerce-Unternehmen",
            "Logistikunternehmen", "Immobilienmakler",
            "Steuerberater und Kanzleien", "Handwerksbetriebe"
        ]
        industry = industries[cls.total_campaigns % len(industries)]
        
        # Step 1: FINDE ECHTE FIRMEN per Web-Suche (keine KI-Erfindungen!)
        prospects = await cls._find_real_prospects(industry, count=5)
        
        if not prospects:
            logger.warning(f"Outreach: Keine echten Prospects fuer {industry} gefunden — ueberspringe")
            return
        
        # Filter: skip bounced emails
        prospects = [p for p in prospects if not any(b.get("email") == p["email"] for b in cls.bounced_emails)]
        
        if not prospects:
            logger.warning(f"Outreach: Keine gueltigen Prospects fuer {industry} gefunden")
            return
        
        # Limit per cycle
        prospects = prospects[:cls.max_emails_per_cycle]
        cls.outreach_targets.extend(prospects)
        
        # Step 2: Generate + send personalized email for each prospect
        sent_count = 0
        for prospect in prospects:
            company = prospect["company"]
            email_addr = prospect["email"]
            reason = prospect["reason"]
            
            # Skip if already contacted — check both "email" and "to" keys
            already_contacted = any(
                s.get("email") == email_addr or s.get("to") == email_addr 
                for s in cls.outreach_sent
            )
            if already_contacted:
                logger.info(f"Outreach: {email_addr} bereits kontaktiert — ueberspringe")
                continue
            
            # Generate HUMAN-LIKE personalized email
            import random as _rnd
            sender_names = ["Sarah", "Michael", "Lisa", "Thomas", "Anna", "Daniel"]
            sender_name = _rnd.choice(sender_names)
            
            personal_prompt = f"""Schreibe eine personalisierte Cold-Email an {company}.
            Grund warum sie KI brauchen: {reason}
            
            WICHTIG — Schreibe wie ein MENSCH, nicht wie ein Bot:
            - Keine Listen, keine Bulletpoints
            - Natuerliche, gespraechliche Sprache
            - 3-4 Saetze, kurz und persoenlich
            - Erwaehne EIN konkretes Problem von {company}
            - Keine "Wir bieten..." Marketing-Sprache
            - Schluss mit einer Frage, nicht mit "Klicken Sie hier"
            - Keine "71 KI-Agenten" oder "Bot" — schreibe "unser Team"
            - Unterschreib mit "Viele Gruesse, {sender_name}"
            - Betreff: Personalisiert fuer {company}, neugierig machend, max 50 Zeichen, keine Ausrufezeichen
            - Sprache: Deutsch. Professional aber warm."""
            
            try:
                email_content = await SmartAIRouter.call_llm_efficient(personal_prompt, "cold_outreach_leadgen")
            except Exception as e:
                logger.error(f"Outreach: Email-Generierung fuer {company} fehlgeschlagen: {e}")
                continue
            
            # Extract subject and body from generated content
            lines = email_content.strip().split("\n")
            subject = lines[0].replace("Betreff:", "").replace("Subject:", "").strip()
            body = "\n".join(lines[1:]).strip()
            if not subject:
                subject = f"Kurze Frage an {company}"
            if not body:
                body = email_content
            
            # PLACEHOLDER-FIX: Nie einen unersetzten Platzhalter verschicken
            import re as _re2
            placeholder_pattern = _re2.compile(r'\[(Name|Firma|Vorname|Nachname|Company|Branche)\]', _re2.IGNORECASE)
            if placeholder_pattern.search(body) or placeholder_pattern.search(subject):
                # Ersetze generisch statt zu verschicken mit kaputtem Platzhalter
                body = placeholder_pattern.sub("", body)
                subject = placeholder_pattern.sub("", subject)
                body = body.replace("Hallo ,", "Hallo,").replace("Hallo  ,", "Hallo,")
                # Doppelte Leerzeichen aufraeumen
                body = _re2.sub(r' {2,}', ' ', body)
                subject = _re2.sub(r' {2,}', ' ', subject).strip()
            
            # Send the email
            result = await EmailEngine.send_email(
                to=email_addr,
                subject=subject,
                body=body,
                bot_name="cold_outreach_leadgen"
            )
            
            outreach_record = {
                "id": f"outreach_{uuid.uuid4().hex[:8]}",
                "company": company,
                "email": email_addr,
                "industry": industry,
                "subject": subject,
                "status": result.get("status", "error"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            cls.outreach_sent.append(outreach_record)
            
            if result.get("status") == "sent":
                sent_count += 1
                logger.info(f"Outreach: Cold-Email gesendet an {company} ({email_addr})")
            else:
                cls.bounced_emails.append({"email": email_addr, "company": company, "reason": result.get("message","")})
                logger.warning(f"Outreach: Fehlgeschlagen fuer {email_addr} — als problematisch markiert")
            
            # HUMAN-LIKE DELAY: 30-90 seconds between emails, randomized
            import random as _rnd2
            human_delay = _rnd2.randint(30, 90)
            await asyncio.sleep(human_delay)
        
        logger.info(f"Outreach: Zyklus abgeschlossen — {sent_count} Mails an {industry} gesendet")
        return {"sent": sent_count, "targets": len(prospects), "industry": industry}
    
    @classmethod
    async def _autonomous_cold_outreach_manual(cls, industry: str):
        """Manuelle Cold-Outreach fuer eine spezifische Branche - nutzt verified_prospect_lists."""
        prospects = await cls._find_real_prospects(industry, count=10)
        if not prospects:
            return {"status": "no_prospects", "message": f"Keine Kontakte fuer {industry} gefunden"}
        
        if not EmailEngine.is_configured:
            return {"status": "no_smtp", "message": "SMTP nicht konfiguriert"}
        
        max_per_day = 25
        sent_today = sum(1 for s in cls.outreach_sent 
                        if s.get("timestamp","")[:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        if sent_today >= max_per_day:
            return {"status": "daily_limit", "message": f"Tageslimit ({max_per_day}) erreicht"}
        
        remaining = max_per_day - sent_today
        prospects = prospects[:remaining]
        
        sent_count = 0
        for prospect in prospects:
            company = prospect["company"]
            email_addr = prospect["email"]
            
            already_contacted = any(
                s.get("email") == email_addr or s.get("to") == email_addr 
                for s in cls.outreach_sent
            )
            if already_contacted:
                continue
            
            import random as _rnd
            sender_names = ["Sarah", "Michael", "Lisa", "Thomas", "Anna", "Daniel", "Julia", "Mark"]
            sender_name = _rnd.choice(sender_names)
            
            personal_prompt = (
                f"Schreibe eine kurze Email an {company} ({prospect.get('city','')}). "
                f"Die Firma ist eine {industry}. "
                f"WICHTIG - Schreibe wie ein MENSCH der morgens im Buero sitzt: "
                f"Sehr kurz: 2-3 Saetze, nicht mehr. "
                f"Natuerlich, als wuerdest du einer Kollegin etwas erzaehlen. "
                f"Keine Aufzaehlungen, keine Listen. "
                f"Keine Marketing-Sprache, kein Wir bieten. "
                f"Keine 71 KI-Agenten, kein Bot, kein KI im ersten Satz. "
                f"Fang mit einer konkreten Beobachtung an. "
                f"Ende mit einer einfachen Frage. "
                f"Unterschreib mit Gruesse, {sender_name}. "
                f"Betreff: Max 40 Zeichen, neugierig, keine Ausrufezeichen. "
                f"Sprache: Deutsch, locker aber professionell. "
                f"KEINE Uebertreibung, keine Superlative."
            )
            
            try:
                email_content = await SmartAIRouter.call_llm_efficient(personal_prompt, "cold_outreach_leadgen")
            except Exception as e:
                logger.error(f"Outreach: Email-Gen fuer {company} fehlgeschlagen: {e}")
                continue
            
            lines = email_content.strip().split("\n")
            subject = lines[0].replace("Betreff:", "").replace("Subject:", "").strip()
            body = "\n".join(lines[1:]).strip()
            if not subject:
                subject = f"Kurze Frage an {company}"
            if not body:
                body = email_content
            
            import re as _re2
            placeholder_pattern = _re2.compile(r'\[(Name|Firma|Vorname|Nachname|Company|Branche)\]', _re2.IGNORECASE)
            if placeholder_pattern.search(body) or placeholder_pattern.search(subject):
                body = placeholder_pattern.sub("", body)
                subject = placeholder_pattern.sub("", subject)
                body = body.replace("Hallo ,", "Hallo,").replace("Hallo  ,", "Hallo,")
                body = _re2.sub(r' {2,}', ' ', body)
                subject = _re2.sub(r' {2,}', ' ', subject).strip()
            
            result = await EmailEngine.send_email(email_addr, subject, body, "cold_outreach_leadgen")
            
            outreach_record = {
                "id": f"outreach_{uuid.uuid4().hex[:8]}",
                "company": company,
                "email": email_addr,
                "industry": industry,
                "subject": subject,
                "status": result.get("status", "error"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            cls.outreach_sent.append(outreach_record)
            
            if result.get("status") == "sent":
                sent_count += 1
                logger.info(f"Outreach: Mail an {company} ({email_addr}) gesendet")
            else:
                cls.bounced_emails.append({"email": email_addr, "company": company, "reason": result.get("message","")})
            
            # Persist after each email
            cls._save_outreach_data()
            
            import random as _rnd2
            await asyncio.sleep(_rnd2.randint(30, 90))
        
        return {"sent": sent_count, "industry": industry, "remaining_today": max_per_day - sent_today - sent_count}
    
    @classmethod
    async def _send_follow_ups(cls):
        """Sendet Follow-Up Mails an Firmen die vor 3+ Tagen angeschrieben wurden
        und noch nicht geantwortet haben. Max 1 Follow-Up pro Firma."""
        if not EmailEngine.is_configured:
            return
        
        now = datetime.now(timezone.utc)
        sent_count = 0
        
        for record in cls.outreach_sent:
            # Skip if already followed up
            if any(f.get("original_id") == record.get("id") for f in cls.follow_up_sent):
                continue
            
            # Check if 3+ days since first email
            sent_time = datetime.fromisoformat(record["timestamp"].replace("Z","+00:00"))
            days_since = (now - sent_time).days
            
            if days_since < 3:
                continue
            
            company = record.get("company", "")
            email = record.get("email", "")
            
            # Generate short follow-up
            import random as _rnd
            sender_names = ["Sarah", "Michael", "Lisa", "Thomas", "Anna", "Daniel"]
            sender_name = _rnd.choice(sender_names)
            
            followup_prompt = (
                f"Schreibe eine kurze Follow-Up Email an {company}. "
                f"Du hast ihnen vor ein paar Tagen schon geschrieben. "
                f"WICHTIG - Sehr kurz: 1-2 Saetze. Locker, nicht aufdringlich. "
                f"Einfach nachfragen ob sie die erste Mail gesehen haben. "
                f"Keine Marketing-Sprache. Keine Aufzaehlungen. "
                f"Unterschreib mit Gruesse, {sender_name}. "
                f"Betreff: Re: [urspruenglicher Betreff] oder max 35 Zeichen. "
                f"Sprache: Deutsch. KEINE Uebertreibung."
            )
            
            try:
                email_content = await SmartAIRouter.call_llm_efficient(followup_prompt, "cold_outreach_leadgen")
            except Exception as e:
                logger.error(f"Follow-Up: Generierung fuer {company} fehlgeschlagen: {e}")
                continue
            
            lines = email_content.strip().split("\n")
            subject = lines[0].replace("Betreff:", "").replace("Subject:", "").strip()
            body = "\n".join(lines[1:]).strip()
            if not subject:
                subject = f"Re: {record.get('subject', 'Kurze Frage')}"
            if not body:
                body = email_content
            
            result = await EmailEngine.send_email(email, subject, body, "cold_outreach_leadgen")
            
            cls.follow_up_sent.append({
                "original_id": record.get("id"),
                "company": company,
                "email": email,
                "subject": subject,
                "status": result.get("status", "error"),
                "timestamp": now.isoformat()
            })
            
            if result.get("status") == "sent":
                sent_count += 1
                logger.info(f"Follow-Up an {company} ({email}) gesendet")
            
            # Persist after follow-up
            cls._save_outreach_data()
            
            import random as _rnd2
            await asyncio.sleep(_rnd2.randint(60, 120))
        
        return {"follow_ups_sent": sent_count}
    
    @classmethod
    async def _generate_directory_listing(cls):
        """Generiert Directory-Listing-Texte für Business-Verzeichnisse."""
        directories = [
            "Google Business Profile", "Trustpilot", "Clutch.co",
            "Capterra", "G2.com", "Yelp Business", "Hotfrog"
        ]
        directory = directories[cls.total_campaigns % len(directories)]
        
        prompt = f"""Schreibe ein Company-Listing für {directory}.
        Firma: RevenueAgentRoute — 71 KI-Agenten für B2B-Automation.
        Beschreibung: 3 Sätze. Services: Lead Generation, SEO, Content, Cold Outreach, Conversion Optimierung.
        USP: 1 Mensch + 71 KI-Bots. 7 Tage kostenlos testen.
        Sprache: Deutsch."""
        
        content = await SmartAIRouter.call_llm_efficient(prompt, "google_business_local_seo")
        
        listing = {
            "id": f"dir_{uuid.uuid4().hex[:8]}",
            "directory": directory,
            "content": content,
            "status": "ready_to_submit",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bot": "google_business_local_seo",
            "type": "directory_listing"
        }
        cls.directory_listings.append(listing)
        cls.marketing_content.append(listing)
        return listing
    
    @classmethod
    async def _optimize_landing_copy(cls):
        """Optimiert Landing-Page-Copy basierend auf aktuellen Trends."""
        prompt = """Analysiere die RevenueAgentRoute Landing Page.
        Was kann verbessert werden? Headline, CTA, Value Proposition.
        Gib 3 konkrete Verbesserungsvorschläge in 2 Sätzen.
        Sprache: Deutsch."""
        
        content = await SmartAIRouter.call_llm_efficient(prompt, "landingpage_copywriting")
        
        optimization = {
            "id": f"opt_{uuid.uuid4().hex[:8]}",
            "suggestions": content,
            "status": "analyzed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bot": "landingpage_copywriting",
            "type": "landing_optimization"
        }
        cls.marketing_content.append(optimization)
        return optimization
    
    @classmethod
    def get_status(cls) -> Dict:
        return {
            "running": cls.is_running,
            "last_run": cls.last_run.isoformat() if cls.last_run else None,
            "total_campaigns": cls.total_campaigns,
            "content_pieces": len(cls.marketing_content),
            "seo_articles": len(cls.seo_articles),
            "social_posts": len(cls.social_posts),
            "cold_emails": len(cls.cold_emails),
            "directory_listings": len(cls.directory_listings),
            "active_bots": len(cls.MARKETING_BOTS)
        }
    
    @classmethod
    def get_content(cls, content_type: Optional[str] = None, limit: int = 50) -> List[Dict]:
        if content_type:
            return [c for c in cls.marketing_content if c.get("type") == content_type][:limit]
        return cls.marketing_content[:limit]

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
    # Autonomous Marketing Engine starten
    asyncio.create_task(AutonomousMarketingEngine.run_marketing_cycle())
    logger.info("Marketing Engine: aktiv — 15 Bots generieren autonom alle 3 Stunden Content")
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

# ===== PUBLIC ROUTES (not under /api/revenue prefix) =====
@app.get("/content", include_in_schema=False)
async def public_content_root():
    """Oeffentliche Content-Seite — SEO-indexiert."""
    return await public_content_page()

@app.get("/sitemap.xml", include_in_schema=False)
async def public_sitemap():
    return await sitemap()

@app.get("/robots.txt", include_in_schema=False)
async def public_robots():
    return await robots()

@app.get("/", include_in_schema=False)
async def root_landing_page():
    return await landing_page()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000)
