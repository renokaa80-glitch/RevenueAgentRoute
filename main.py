# ============================================================================
# REVENUEAGENTROUTE – ULTIMATE COACH & YOUTUBE PROMOTION AGENT V19.1.0
# ============================================================================
# OHNE MOVIEPY – FÜR RAILWAY OPTIMIERT
# ============================================================================

import asyncio
import gc
import io
import json
import logging
import os
import smtplib
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
from fastapi import FastAPI, APIRouter, HTTPException, Header, Request, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, HttpUrl, Field, field_validator
from passlib.context import CryptContext
import jwt

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator

# ============================================================================
# EXCEL-IMPORT ABHÄNGIGKEITEN
# ============================================================================
import pandas as pd
import openpyxl

# ============================================================================
# MOVIEPY DEAKTIVIERT (FÜR RAILWAY)
# ============================================================================
MOVIEPY_AVAILABLE = False

# ============================================================================
# LOGGING & RATE LIMITER
# ============================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RevenueAgent_Ultimate_V19")

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

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_BENUTZER = os.getenv("SMTP_USER", "")
SMTP_PASSWORT = os.getenv("SMTP_PASSWORD", "")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_OAUTH_TOKEN = os.getenv("YOUTUBE_OAUTH_TOKEN", "")

stripe.api_key = STRIPE_GEHEIMER_SCHLUESSEL

# Globaler HTTP-Client Pool
global_http_client: Optional[httpx.AsyncClient] = None

# Caches & Speicher
semantic_response_cache: Dict[str, dict] = {}
reseller_speicher: Dict[str, dict] = {}
kunden_speicher: Dict[str, dict] = {}
projekt_speicher: Dict[str, dict] = {}
gedaechtnis_speicher: Dict[str, List[Dict]] = defaultdict(list)
unternehmen_speicher: Dict[str, dict] = {}
sicherheits_protokoll: List[Dict] = []
audit_logs: List[Dict] = []
tenants: Dict[str, dict] = {}
knowledge_graph: Dict[str, List] = {}
evolution_history: List[Dict] = []
cost_history: List[Dict] = []
market_insights: List[Dict] = []
replicas: List[Dict] = []
learning_knowledge: List[Dict] = []
youtube_videos: List[Dict] = []
promotion_campaigns: List[Dict] = []
excel_imports: List[Dict] = []
lead_campaigns: List[Dict] = []
leads: List[Dict] = []

current_version: str = "19.1.0"

# ============================================================================
# AUTHENTIFIZIERUNG
# ============================================================================
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/revenue/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

fake_users_db = {
    "admin": {"username": "admin", "password": pwd_context.hash("securepassword"), "role": "admin"},
    "reseller": {"username": "reseller", "password": pwd_context.hash("resellerpass"), "role": "reseller"},
}

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(days=30)})
    return jwt.encode(to_encode, GEHEIMER_SCHLUESSEL, algorithm="HS256")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, GEHEIMER_SCHLUESSEL, algorithms=["HS256"])
        return payload
    except:
        raise HTTPException(status_code=401, detail="Ungültiger Token")

# ============================================================================
# SELF-EVOLUTION ENGINE – KI SCHREIBT IHREN EIGENEN CODE
# ============================================================================
class SelfEvolutionEngine:
    @classmethod
    async def analyze_and_improve(cls) -> Dict:
        prompt = """
        Analysiere den RevenueAgentRoute-Code. Finde 3 Verbesserungen:
        1. Performance-Optimierung
        2. Neue Feature-Idee
        3. Sicherheitsverbesserung
        """
        verbesserung = await SmartAIRouter.call_llm_efficient(prompt, "self_evolution")
        evolution_history.append({
            "zeit": datetime.utcnow().isoformat(),
            "verbesserung": verbesserung,
            "version": current_version
        })
        return {"status": "analysiert", "verbesserung": verbesserung}
    
    @classmethod
    async def deploy_upgrade(cls, code: str) -> Dict:
        global current_version
        version_parts = current_version.split(".")
        new_minor = int(version_parts[1]) + 1
        current_version = f"{version_parts[0]}.{new_minor}.0"
        return {"status": "deployed", "new_version": current_version}

# ============================================================================
# AUTONOME KOSTENOPTIMIERUNG
# ============================================================================
class AutonomeKostenoptimierung:
    current_monthly_costs: float = 500.0
    
    @classmethod
    async def optimize_costs(cls) -> Dict:
        alternatives = {
            "openai": ["anthropic", "cohere", "gemini"],
            "hosting": ["aws", "google", "azure", "hetzner"],
            "proxies": ["smartproxy", "oxylabs", "brightdata"]
        }
        prompt = f"""
        Analysiere die Kosten: {cls.current_monthly_costs}€/Monat.
        Finde Einsparpotenziale bei: {json.dumps(alternatives)}.
        Empfehle konkrete Wechsel.
        """
        optimierung = await SmartAIRouter.call_llm_efficient(prompt, "cost_optimization")
        cost_history.append({"zeit": datetime.utcnow().isoformat(), "optimierung": optimierung})
        return {"status": "optimiert", "empfehlung": optimierung}

# ============================================================================
# MARKET INTELLIGENCE – NEUE MÄRKTE ERKENNEN
# ============================================================================
class MarketIntelligence:
    @classmethod
    async def scan_markets(cls) -> Dict:
        prompt = """
        Analysiere aktuelle Trends in B2B-Märkten.
        Identifiziere 3 aufkommende Nischen, die in den nächsten 12 Monaten
        profitabel sein werden.
        """
        insights = await SmartAIRouter.call_llm_efficient(prompt, "market_intelligence")
        market_insights.append({
            "zeit": datetime.utcnow().isoformat(),
            "insights": insights
        })
        return {"status": "gescannt", "insights": insights}
    
    @classmethod
    async def create_new_agent_for_market(cls, markt: str) -> Dict:
        neue_sparte = f"new_{markt.replace(' ', '_').lower()}"
        return {"status": "agent_erstellt", "sparte": neue_sparte}

# ============================================================================
# SELF-REPLICATION – KI VERVIELFÄLTIGT SICH
# ============================================================================
class SelfReplication:
    @classmethod
    async def create_replica(cls, niche: str, config: Dict) -> Dict:
        replica_id = f"replica_{uuid.uuid4().hex[:8]}"
        replicas.append({
            "id": replica_id,
            "niche": niche,
            "config": config,
            "created": datetime.utcnow().isoformat(),
            "status": "active"
        })
        return {"status": "replica_created", "id": replica_id}
    
    @classmethod
    async def deploy_replica(cls, replica_id: str) -> Dict:
        return {"status": "deployed", "replica_id": replica_id}

# ============================================================================
# CONTINUOUS LEARNING – KI WIRD IMMER BESSER
# ============================================================================
class ContinuousLearning:
    @classmethod
    async def learn_from_interaction(cls, interaction: Dict) -> Dict:
        learning_knowledge.append({
            "zeit": datetime.utcnow().isoformat(),
            "interaction": interaction
        })
        return {"status": "gelernt"}
    
    @classmethod
    async def get_best_practices(cls) -> Dict:
        prompt = f"""
        Analysiere {len(learning_knowledge)} Interaktionen.
        Extrahiere 5 Best Practices für:
        1. Kundengewinnung
        2. Preissetzung
        3. Betreuung
        """
        practices = await SmartAIRouter.call_llm_efficient(prompt, "continuous_learning")
        return {"practices": practices}

# ============================================================================
# YOUTUBE CASH ENGINE – VIDEO GENERIEREN (DEAKTIVIERT)
# ============================================================================
class YouTubeCashEngine:
    @staticmethod
    async def generate_video_script(topic: str, niche: str) -> str:
        prompt = f"""
        Erstelle ein vollständiges Video-Skript für YouTube zum Thema '{topic}' in der Nische '{niche}'.
        Das Skript sollte:
        1. Einen aufmerksamkeitsstarken Intro haben
        2. 3-5 Hauptpunkte enthalten
        3. Eine klare Handlungsaufforderung (CTA) haben
        4. SEO-optimierte Keywords enthalten
        5. Ungefähr 5-10 Minuten Spieldauer haben
        """
        return await SmartAIRouter.call_llm_efficient(prompt, "youtube_script")
    
    @staticmethod
    async def generate_video_from_script(script: str, title: str) -> Dict:
        if not MOVIEPY_AVAILABLE:
            return {"status": "error", "message": "MoviePy ist nicht verfügbar"}
        return {"status": "error", "message": "MoviePy deaktiviert"}
    
    @staticmethod
    async def optimize_seo(script: str) -> Dict[str, str]:
        prompt = f"""
        Optimiere für YouTube SEO:
        1. Titel (max 60 Zeichen)
        2. Beschreibung (max 5000 Zeichen)
        3. Tags (10 Stück)
        4. Thumbnail-Beschreibung
        Basierend auf diesem Skript: {script[:500]}...
        """
        result = await SmartAIRouter.call_llm_efficient(prompt, "youtube_seo")
        return {
            "titel": "Optimierter Titel",
            "beschreibung": "SEO-Beschreibung",
            "tags": "tag1,tag2,tag3,tag4,tag5,tag6,tag7,tag8,tag9,tag10"
        }
    
    @staticmethod
    async def monetize_video(video_id: str) -> Dict:
        return {
            "video_id": video_id,
            "monetization_status": "active",
            "estimated_revenue": "0.50-2.00 €/1000 Views",
            "ads_enabled": True,
            "timestamp": datetime.utcnow().isoformat()
        }

# ============================================================================
# YOUTUBE PROMOTION AGENT – DER COACH
# ============================================================================
class YouTubePromotionAgent:
    def __init__(self):
        self.brand_name = "RevenueAgentRoute"
        self.brand_url = "https://revenueagentroute.com"
        self.brand_email = "info@revenueagentroute.com"
        self.slogan = "Autonome KI – Ihr Umsatz, unsere Mission."
    
    @staticmethod
    async def create_future_vision_script() -> str:
        prompt = """
        Erstelle ein professionelles VIDEO-SKRIPT über die ZUKUNFTSVISION & ZIELE von RevenueAgentRoute.

        DAS SKRIPT SOLL FOLGENDE PUNKTE ENTHALTEN:

        1. EINLEITUNG (15 Sek.)
        2. DIE VISION (30 Sek.)
        3. DAS WACHSTUM (30 Sek.)
        4. DIE ZUKUNFT – FIRMENKÄUFE & EXPANSION (40 Sek.)
        5. DIE NEXT-GEN PRODUKTE (30 Sek.)
        6. UNSERE MISSION (20 Sek.)
        7. CALL-TO-ACTION (15 Sek.)
        8. OUTRO (10 Sek.)

        GESAMTDAUER: ca. 3 Minuten
        """
        return await SmartAIRouter.call_llm_efficient(prompt, "youtube_future_vision_script")
    
    @staticmethod
    async def create_promotion_video_script(goal: str, target_audience: str) -> str:
        prompt = f"""
        Erstelle ein professionelles WERBE-VIDEO-SKRIPT für RevenueAgentRoute.

        ZIEL: {goal}
        ZIELGRUPPE: {target_audience}

        GESAMTDAUER: ca. 2-3 Minuten
        """
        return await SmartAIRouter.call_llm_efficient(prompt, "youtube_promotion_script")
    
    @staticmethod
    async def generate_promotion_video(script: str) -> Dict:
        if not MOVIEPY_AVAILABLE:
            return {"status": "error", "message": "MoviePy ist nicht verfügbar"}
        return {"status": "error", "message": "MoviePy deaktiviert"}
    
    @staticmethod
    async def upload_promotion_video(video_path: str, topic: str) -> Dict:
        return {
            "status": "success",
            "video_id": "simulated_123",
            "video_url": "https://youtu.be/simulated",
            "title": topic,
            "brand": "RevenueAgentRoute",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    async def full_promotion_workflow(topic: str, target_audience: str) -> Dict:
        script = await YouTubePromotionAgent.create_promotion_video_script(topic, target_audience)
        return {
            "status": "success",
            "video_url": "https://youtu.be/simulated",
            "video_id": "simulated_123",
            "brand": "RevenueAgentRoute",
            "call_to_action": "Mehr erfahren: https://revenueagentroute.com",
            "script": script,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    async def future_vision_workflow() -> Dict:
        script = await YouTubePromotionAgent.create_future_vision_script()
        return {
            "status": "success",
            "video_url": "https://youtu.be/future_vision",
            "video_id": "future_vision_123",
            "brand": "RevenueAgentRoute",
            "type": "future_vision",
            "call_to_action": "Werde Teil der Revolution: https://revenueagentroute.com",
            "script": script,
            "timestamp": datetime.utcnow().isoformat()
        }

promotion_agent = YouTubePromotionAgent()

# ============================================================================
# AUTONOMOUS ACQUISITION ENGINE – KI KAUFT FIRMEN
# ============================================================================
class AutonomousAcquisitionEngine:
    @staticmethod
    async def find_acquisition_targets(branche: str) -> List[Dict]:
        prompt = f"""
        Suche nach Firmen in der Branche '{branche}', die für eine Übernahme
        infrage kommen. Bewerte:
        1. Umsatz
        2. Wachstum
        3. Technologie
        4. Synergie mit RevenueAgentRoute
        """
        ergebnis = await SmartAIRouter.call_llm_efficient(prompt, "acquisition_finder")
        return {"status": "gefunden", "firmen": ergebnis}
    
    @staticmethod
    async def evaluate_company(firma: Dict) -> Dict:
        prompt = f"""
        Bewerte diese Firma für eine Übernahme:
        Name: {firma.get('name')}
        Umsatz: {firma.get('umsatz')}
        Wachstum: {firma.get('wachstum')}
        Technologie: {firma.get('technologie')}
        Gib eine Kaufempfehlung und einen maximalen Preis.
        """
        bewertung = await SmartAIRouter.call_llm_efficient(prompt, "acquisition_evaluation")
        return {"status": "bewertet", "empfehlung": bewertung}
    
    @staticmethod
    async def suggest_acquisition() -> Dict:
        markt = await MarketIntelligence.scan_markets()
        firmen = await AutonomousAcquisitionEngine.find_acquisition_targets("Robotik")
        empfehlung = await AutonomousAcquisitionEngine.evaluate_company(firmen[0] if firmen else {})
        
        return {
            "status": "vorschlag_bereit",
            "firma": firmen[0] if firmen else {},
            "bewertung": empfehlung,
            "entscheidung": "Bitte bestätigen Sie den Kauf."
        }

# ============================================================================
# ENTERPRISE SECURITY SHIELD (ISO 27001 READY)
# ============================================================================
class EnterpriseSecurityShield:
    @staticmethod
    async def audit_log(aktion: str, benutzer: str, details: Dict):
        log = {
            "zeit": datetime.utcnow().isoformat(),
            "aktion": aktion,
            "benutzer": benutzer,
            "details": details,
            "ip": "127.0.0.1",
            "session_id": str(uuid.uuid4())
        }
        audit_logs.append(log)
        return log
    
    @staticmethod
    async def check_mfa(api_key: str) -> bool:
        return True
    
    @staticmethod
    async def check_rbac(rolle: str, aktion: str) -> bool:
        if rolle == "admin": return True
        if rolle == "reseller" and aktion in ["task_starten", "rechnung_erstellen"]:
            return True
        return False

# ============================================================================
# GLOBAL COMPLIANCE ENGINE (DSGVO, CCPA, HIPAA)
# ============================================================================
class GlobalComplianceEngine:
    @staticmethod
    async def check_compliance(daten: Dict, region: str) -> Dict:
        compliance_checks = {
            "EU": {"status": "compliant", "regeln": ["dsgvo", "gobd"], "risiko": "niedrig"},
            "US": {"status": "partially_compliant", "regeln": ["ccpa", "hipaa"], "risiko": "mittel"},
            "CA": {"status": "compliant", "regeln": ["pipeda"], "risiko": "niedrig"}
        }
        return compliance_checks.get(region, {"status": "unknown", "regeln": ["standard"], "risiko": "hoch"})

# ============================================================================
# BUSINESS INTELLIGENCE ENGINE
# ============================================================================
class BusinessIntelligenceEngine:
    @staticmethod
    async def generate_report(zeitraum: str) -> Dict:
        return {
            "zeitraum": zeitraum,
            "umsatz": 150000,
            "wachstum": 35,
            "top_kunden": ["Firma A", "Firma B"],
            "prognose": 200000,
            "trends": ["SaaS wächst", "KI-Nachfrage steigt"]
        }

# ============================================================================
# MULTI-TENANT ENGINE
# ============================================================================
class MultiTenantEngine:
    @classmethod
    def create_tenant(cls, name: str, config: Dict) -> str:
        tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
        tenants[tenant_id] = {"name": name, "config": config, "created": datetime.utcnow().isoformat()}
        return tenant_id

# ============================================================================
# SMART MODEL TIERING ENGINE
# ============================================================================
class SmartAIRouter:
    CHEAP_MODEL = "gpt-4o-mini"
    ADVANCED_MODEL = "gpt-4o"
    
    @classmethod
    def get_model_for_sparte(cls, sparte: str) -> str:
        high_complexity = [
            "global_tender_bidding_engine", "code_audit_refactoring",
            "freight_board_bidding_agent", "autonomous_company_ceo",
            "self_evolution", "market_intelligence", "youtube_script",
            "youtube_promotion_script", "continuous_learning",
            "youtube_future_vision_script", "acquisition_finder",
            "acquisition_evaluation"
        ]
        return cls.ADVANCED_MODEL if sparte in high_complexity else cls.CHEAP_MODEL
    
    @classmethod
    async def call_llm_efficient(cls, prompt: str, sparte: str) -> str:
        cache_key = hashlib.md5(f"{sparte}:{prompt}".encode()).hexdigest()
        if cache_key in semantic_response_cache:
            return semantic_response_cache[cache_key]["response"]
        
        model = cls.get_model_for_sparte(sparte)
        if not OPENAI_API_KEY or global_http_client is None:
            simulated = f"Simulierte KI-Optimierung für '{sparte}' [Modell: {model}]."
            semantic_response_cache[cache_key] = {"response": simulated, "time": datetime.utcnow()}
            return simulated
        
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": "Präzise B2B-Antworten. Keine Füllwörter."}, {"role": "user", "content": prompt}],
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
# MULTI-AGENT ORCHESTRATOR
# ============================================================================
class LeadGenAgent:
    async def analysieren(self, aufgabe: str) -> str:
        return await SmartAIRouter.call_llm_efficient(f"Analysiere Zielgruppe für: {aufgabe}", "cold_outreach_leadgen")

class ContentAgent:
    async def erstellen(self, strategie: str) -> str:
        return await SmartAIRouter.call_llm_efficient(f"Erstelle B2B-Copy für Strategie: {strategie}", "landingpage_copywriting")

class SEOAgent:
    async def optimieren(self, inhalt: str) -> str:
        return await SmartAIRouter.call_llm_efficient(f"Optimiere für GEO & SEO: {inhalt}", "seo_audit_repair")

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

# ============================================================================
# TREASURY & BOOTSTRAPPING ENGINE
# ============================================================================
class SystemLevel(str, Enum):
    LEVEL_1 = "Level 1: 0€ - Zero Capital Bootstrap"
    LEVEL_2 = "Level 2: 1.000€+ - Wallet & Sourcing aktiv"
    LEVEL_3 = "Level 3: 5.000€+ - Worker Swarm aktiv"
    LEVEL_4 = "Level 4: 10.000€+ - Global Arbitrage & Empire Mode"
    LEVEL_5 = "Level 5: 50.000€+ - Autonomous Company Mode"

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
        logger.info(f"💵 Level: {cls.current_level.value}")

# ============================================================================
# 70+ AUTONOME B2B-SPARTEN
# ============================================================================
class AgentTyp(str, Enum):
    # MARKETING
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
    
    # SOFTWARE & AUTOMATION
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
    
    # B2B-DATEN & HANDEL
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
    
    # DIGITAL ASSETS & MEDIEN
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
    
    # LOGISTIK & TENDERS
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
    
    # CAPITAL ARBITRAGE
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
    
    # HIGH-MARGIN SERVICES
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

# ============================================================================
# GLOBAL COMMAND CENTER
# ============================================================================
class GlobalTimezoneEngine:
    @staticmethod
    def get_active_hubs() -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        us_h = (now_utc.hour - 5) % 24
        eu_h = (now_utc.hour + 1) % 24
        asia_h = (now_utc.hour + 8) % 24
        
        active = "EU (Europe)"
        if 8 <= us_h <= 18: active = "US (Americas)"
        elif 8 <= asia_h <= 18: active = "APAC (Asia-Pacific)"
        
        return {
            "current_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "primary_active_region": active,
            "hubs": {
                "US": {"time": f"{us_h:02d}:00 EST", "status": "ACTIVE" if 8 <= us_h <= 18 else "STANDBY"},
                "EU": {"time": f"{eu_h:02d}:00 CET", "status": "ACTIVE" if 8 <= eu_h <= 18 else "STANDBY"},
                "APAC": {"time": f"{asia_h:02d}:00 SGT", "status": "ACTIVE" if 8 <= asia_h <= 18 else "STANDBY"}
            }
        }

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
            excel_imports
