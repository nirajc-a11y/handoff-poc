"""Seed script: creates VSynergize tenant with agents, IVR menus, campaign, and leads."""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.db.models import *  # noqa: F401, F403


async def seed():
    engine = create_async_engine(settings.database_url, echo=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # Check if VSynergize tenant already exists
        existing = (await db.execute(
            select(Tenant).where(Tenant.slug == "vsynergize")
        )).scalar_one_or_none()
        if existing:
            print(f"VSynergize tenant already exists (id={existing.id}). Skipping seed.")
            await engine.dispose()
            return

        # ── Tenant ──────────────────────────────────────────────────
        tenant_id = uuid.uuid4()
        tenant = Tenant(
            id=tenant_id,
            name="VSynergize",
            slug="vsynergize",
            status="active",
            config={
                "providers": {"telephony": "plivo"},
                "telephony_provider": "plivo",
                "ai_confidence_threshold": 0.7,
                "default_language": "en",
                "supported_languages": ["en", "hi"],
                "groq_model": "llama-3.3-70b-versatile",
                "ai_system_prompt": (
                    "You are Priya, a professional customer support and sales assistant for VSynergize, "
                    "a leading B2B demand generation and sales acceleration company. "
                    "VSynergize helps businesses grow their pipeline through lead generation, "
                    "appointment setting, content syndication, data services, and ABM campaigns. "
                    "Our offices are in Pune, India and we serve clients globally. "
                    "Website: https://vsynergize.com/. "
                    "Be helpful, professional, and knowledgeable about B2B sales and marketing services."
                ),
                "company_info": {
                    "website": "https://vsynergize.com/",
                    "industry": "B2B Demand Generation & Sales Acceleration",
                    "headquarters": "Pune, Maharashtra, India",
                    "services": [
                        "Lead Generation",
                        "Appointment Setting",
                        "Content Syndication",
                        "Data Services & Intent Data",
                        "Account-Based Marketing (ABM)",
                        "Inside Sales as a Service",
                        "Market Research",
                    ],
                },
            },
        )
        db.add(tenant)
        await db.flush()

        # ── Agents ──────────────────────────────────────────────────
        agents_data = [
            {
                "name": "Priya Sharma",
                "email": "priya.sharma@vsynergize.com",
                "team": "demand-gen",
                "skills": ["lead_generation", "content_syndication", "abm"],
            },
            {
                "name": "Rahul Mehta",
                "email": "rahul.mehta@vsynergize.com",
                "team": "inside-sales",
                "skills": ["appointment_setting", "inside_sales", "cold_calling"],
            },
            {
                "name": "Sneha Patil",
                "email": "sneha.patil@vsynergize.com",
                "team": "demand-gen",
                "skills": ["data_services", "intent_data", "market_research"],
            },
            {
                "name": "Amit Deshmukh",
                "email": "amit.deshmukh@vsynergize.com",
                "team": "inside-sales",
                "skills": ["inside_sales", "appointment_setting", "lead_qualification"],
            },
            {
                "name": "Neha Kulkarni",
                "email": "neha.kulkarni@vsynergize.com",
                "team": "client-success",
                "skills": ["account_management", "billing", "onboarding"],
            },
            {
                "name": "Vikram Joshi",
                "email": "vikram.joshi@vsynergize.com",
                "team": "inside-sales",
                "skills": ["cold_calling", "lead_qualification", "appointment_setting"],
            },
        ]

        agent_ids = []
        for agent_data in agents_data:
            user_id = uuid.uuid4()
            user = User(
                id=user_id,
                tenant_id=tenant_id,
                email=agent_data["email"],
                name=agent_data["name"],
                role="agent",
            )
            db.add(user)

            agent_id = uuid.uuid4()
            profile = AgentProfile(
                id=agent_id,
                user_id=user_id,
                tenant_id=tenant_id,
                skills=agent_data["skills"],
                max_concurrent=2,
                team=agent_data["team"],
            )
            db.add(profile)

            status = AgentStatus(
                id=uuid.uuid4(),
                agent_id=agent_id,
                tenant_id=tenant_id,
                status="available",
                current_conversations=0,
                last_status_change=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(status)
            agent_ids.append(agent_id)

        # Supervisor
        supervisor = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="niraj@vsynergize.com",
            name="Niraj Chordia",
            role="supervisor",
        )
        db.add(supervisor)
        await db.flush()

        # ── IVR Menus (Bilingual: English + Hindi) ─────────────────

        en_menu_id = uuid.uuid4()
        hi_menu_id = uuid.uuid4()

        # Root menu: Language selection
        lang_menu_id = uuid.uuid4()
        lang_menu = IVRMenu(
            id=lang_menu_id,
            tenant_id=tenant_id,
            name="Language Selection",
            is_root=True,
            welcome_message=(
                "Thank you for calling VSynergize, your partner in B2B demand generation "
                "and sales acceleration. For English, press 1. "
                "VSynergize में कॉल करने के लिए धन्यवाद। हिंदी के लिए, 2 दबाएं।"
            ),
            config={"timeout": 10, "retries": 3},
        )
        db.add(lang_menu)

        # Language options
        db.add(IVRMenuOption(
            id=uuid.uuid4(), menu_id=lang_menu_id, tenant_id=tenant_id,
            digit="1", label="English", action_type="submenu",
            target_id=en_menu_id,
            target_config={"language": "en"},
            sort_order=0,
        ))
        db.add(IVRMenuOption(
            id=uuid.uuid4(), menu_id=lang_menu_id, tenant_id=tenant_id,
            digit="2", label="Hindi", action_type="submenu",
            target_id=hi_menu_id,
            target_config={"language": "hi"},
            sort_order=1,
        ))

        # English Main Menu
        en_menu = IVRMenu(
            id=en_menu_id,
            tenant_id=tenant_id,
            name="English Main Menu",
            is_root=False,
            welcome_message=(
                "Please listen carefully. "
                "To learn about our demand generation and lead generation services, press 1. "
                "For appointment setting and inside sales, press 2. "
                "For data services and intent data solutions, press 3. "
                "For billing or account enquiries, press 4. "
                "To speak directly with a representative, press 0. "
                "To hear these options again, press hash."
            ),
            config={"timeout": 12, "retries": 3},
        )
        db.add(en_menu)

        # English options
        for digit, label, action, config in [
            ("1", "Demand Generation", "ai_handoff", {
                "queue_name": "demand-gen",
                "skill_requirements": ["lead_generation", "content_syndication"],
                "language": "en",
                "greeting": (
                    "Welcome to VSynergize Demand Generation. I'm your AI assistant. "
                    "I can help you with lead generation, content syndication, "
                    "account-based marketing, and pipeline acceleration solutions. "
                    "How can I help you today?"
                ),
            }),
            ("2", "Inside Sales & Appointments", "ai_handoff", {
                "queue_name": "inside-sales",
                "skill_requirements": ["appointment_setting", "inside_sales"],
                "language": "en",
                "greeting": (
                    "You've reached VSynergize Inside Sales. I'm your AI assistant. "
                    "I can help you with appointment setting services, inside sales support, "
                    "cold calling campaigns, and sales development. "
                    "What would you like to know?"
                ),
            }),
            ("3", "Data Services", "ai_handoff", {
                "queue_name": "data-services",
                "skill_requirements": ["data_services", "intent_data"],
                "language": "en",
                "greeting": (
                    "Welcome to VSynergize Data Services. I'm your AI assistant. "
                    "I can help with B2B data solutions, intent data, market research, "
                    "and contact database services. "
                    "How may I assist you?"
                ),
            }),
            ("4", "Billing & Accounts", "ai_handoff", {
                "queue_name": "client-success",
                "skill_requirements": ["billing", "account_management"],
                "language": "en",
                "greeting": (
                    "Welcome to VSynergize Client Services. I'm your AI assistant. "
                    "I can help with billing enquiries, account management, "
                    "and onboarding questions. "
                    "What can I help you with?"
                ),
            }),
            ("0", "Speak to a representative", "human_queue", {
                "queue_name": "general",
                "language": "en",
            }),
            ("#", "Repeat menu", "play_message", {
                "message": "Let me repeat the menu options for you.",
                "language": "en",
            }),
        ]:
            db.add(IVRMenuOption(
                id=uuid.uuid4(), menu_id=en_menu_id, tenant_id=tenant_id,
                digit=digit, label=label, action_type=action,
                target_config=config, sort_order=int(digit) if digit.isdigit() else 9,
            ))

        # Hindi Main Menu
        hi_menu = IVRMenu(
            id=hi_menu_id,
            tenant_id=tenant_id,
            name="Hindi Main Menu",
            is_root=False,
            welcome_message=(
                "कृपया ध्यान से सुनें। "
                "डिमांड जनरेशन और लीड जनरेशन सेवाओं के लिए, 1 दबाएं। "
                "अपॉइंटमेंट सेटिंग और इनसाइड सेल्स के लिए, 2 दबाएं। "
                "डेटा सर्विसेज और इंटेंट डेटा के लिए, 3 दबाएं। "
                "बिलिंग या खाता संबंधी पूछताछ के लिए, 4 दबाएं। "
                "प्रतिनिधि से सीधे बात करने के लिए, 0 दबाएं। "
                "ये विकल्प दोबारा सुनने के लिए, हैश दबाएं।"
            ),
            config={"timeout": 12, "retries": 3},
        )
        db.add(hi_menu)

        # Hindi options
        for digit, label, action, config in [
            ("1", "डिमांड जनरेशन", "ai_handoff", {
                "queue_name": "demand-gen",
                "skill_requirements": ["lead_generation", "content_syndication"],
                "language": "hi",
                "greeting": (
                    "VSynergize डिमांड जनरेशन में आपका स्वागत है। मैं आपका AI सहायक हूं। "
                    "मैं लीड जनरेशन, कंटेंट सिंडिकेशन, अकाउंट-बेस्ड मार्केटिंग, "
                    "और पाइपलाइन एक्सेलेरेशन में आपकी मदद कर सकता हूं। "
                    "आज मैं आपकी कैसे मदद कर सकता हूं?"
                ),
            }),
            ("2", "इनसाइड सेल्स", "ai_handoff", {
                "queue_name": "inside-sales",
                "skill_requirements": ["appointment_setting", "inside_sales"],
                "language": "hi",
                "greeting": (
                    "VSynergize इनसाइड सेल्स में आपका स्वागत है। मैं आपका AI सहायक हूं। "
                    "मैं अपॉइंटमेंट सेटिंग, इनसाइड सेल्स सपोर्ट, "
                    "कोल्ड कॉलिंग कैंपेन और सेल्स डेवलपमेंट में मदद कर सकता हूं। "
                    "आप क्या जानना चाहेंगे?"
                ),
            }),
            ("3", "डेटा सर्विसेज", "ai_handoff", {
                "queue_name": "data-services",
                "skill_requirements": ["data_services", "intent_data"],
                "language": "hi",
                "greeting": (
                    "VSynergize डेटा सर्विसेज में आपका स्वागत है। मैं आपका AI सहायक हूं। "
                    "मैं B2B डेटा सॉल्यूशंस, इंटेंट डेटा, मार्केट रिसर्च, "
                    "और कॉन्टैक्ट डेटाबेस सेवाओं में मदद कर सकता हूं। "
                    "मैं आपकी कैसे सहायता कर सकता हूं?"
                ),
            }),
            ("4", "बिलिंग और खाता", "ai_handoff", {
                "queue_name": "client-success",
                "skill_requirements": ["billing", "account_management"],
                "language": "hi",
                "greeting": (
                    "VSynergize क्लाइंट सर्विसेज में आपका स्वागत है। मैं आपका AI सहायक हूं। "
                    "मैं बिलिंग पूछताछ, खाता प्रबंधन, "
                    "और ऑनबोर्डिंग से जुड़े सवालों में मदद कर सकता हूं। "
                    "मैं आपकी क्या मदद कर सकता हूं?"
                ),
            }),
            ("0", "प्रतिनिधि से बात करें", "human_queue", {
                "queue_name": "general",
                "language": "hi",
            }),
            ("#", "मेनू दोबारा सुनें", "play_message", {
                "message": "मैं आपको मेनू विकल्प दोबारा बताता हूं।",
                "language": "hi",
            }),
        ]:
            db.add(IVRMenuOption(
                id=uuid.uuid4(), menu_id=hi_menu_id, tenant_id=tenant_id,
                digit=digit, label=label, action_type=action,
                target_config=config, sort_order=int(digit) if digit.isdigit() else 9,
            ))

        # ── Leads (B2B prospects) ───────────────────────────────────
        leads_data = [
            {
                "name": "Rajesh Kumar",
                "phone": "+919820100001",
                "email": "rajesh.kumar@techcorp.in",
                "whatsapp_number": "+919820100001",
                "metadata_": {"source": "website_inquiry", "company": "TechCorp India", "interest": "lead_generation"},
            },
            {
                "name": "Anita Verma",
                "phone": "+919820100002",
                "email": "anita.verma@globalsoft.com",
                "whatsapp_number": "+919820100002",
                "metadata_": {"source": "linkedin_campaign", "company": "GlobalSoft", "interest": "appointment_setting"},
            },
            {
                "name": "David Chen",
                "phone": "+14155550101",
                "email": "david.chen@bayareatech.com",
                "whatsapp_number": "+14155550101",
                "metadata_": {"source": "content_syndication", "company": "Bay Area Tech", "interest": "abm"},
            },
            {
                "name": "Meera Iyer",
                "phone": "+919820100003",
                "email": "meera.iyer@startupx.io",
                "whatsapp_number": "+919820100003",
                "metadata_": {"source": "webinar_attendee", "company": "StartupX", "interest": "data_services"},
            },
            {
                "name": "James Wilson",
                "phone": "+442071230001",
                "email": "james.wilson@ukfinance.co.uk",
                "whatsapp_number": "+442071230001",
                "metadata_": {"source": "referral", "company": "UK Finance Ltd", "interest": "inside_sales"},
            },
            {
                "name": "Pooja Desai",
                "phone": "+919820100004",
                "email": "pooja.desai@infrabuild.in",
                "whatsapp_number": "+919820100004",
                "metadata_": {"source": "trade_show", "company": "InfraBuild", "interest": "lead_generation"},
            },
            {
                "name": "Michael Brown",
                "phone": "+12125550102",
                "email": "michael.brown@nysales.com",
                "whatsapp_number": "+12125550102",
                "metadata_": {"source": "cold_outreach", "company": "NY Sales Inc", "interest": "content_syndication"},
            },
            {
                "name": "Sunita Reddy",
                "phone": "+919820100005",
                "email": "sunita.reddy@cloudnine.tech",
                "whatsapp_number": "+919820100005",
                "metadata_": {"source": "website_inquiry", "company": "CloudNine Tech", "interest": "intent_data"},
            },
            {
                "name": "Robert Taylor",
                "phone": "+14085550103",
                "email": "robert.taylor@svstartup.com",
                "whatsapp_number": "+14085550103",
                "metadata_": {"source": "partner_referral", "company": "SV Startup", "interest": "abm"},
            },
            {
                "name": "Kavita Nair",
                "phone": "+919820100006",
                "email": "kavita.nair@pharmaindia.com",
                "whatsapp_number": "+919820100006",
                "metadata_": {"source": "email_campaign", "company": "Pharma India", "interest": "appointment_setting"},
            },
        ]

        lead_ids = []
        for lead_data in leads_data:
            lead_id = uuid.uuid4()
            db.add(Lead(
                id=lead_id,
                tenant_id=tenant_id,
                name=lead_data["name"],
                phone=lead_data["phone"],
                email=lead_data["email"],
                whatsapp_number=lead_data["whatsapp_number"],
                metadata_=lead_data["metadata_"],
            ))
            lead_ids.append(lead_id)

        await db.flush()

        # ── Campaign ────────────────────────────────────────────────
        campaign_id = uuid.uuid4()
        campaign = Campaign(
            id=campaign_id,
            tenant_id=tenant_id,
            name="Q2 B2B Pipeline Acceleration",
            status="active",
            type="outbound_call",
            config={
                "dial_mode": "preview",
                "max_retries": 3,
                "retry_delay_minutes": 60,
                "description": "Outbound campaign targeting B2B prospects for demand gen services",
            },
        )
        db.add(campaign)
        await db.flush()

        # Assign leads to campaign (round-robin across agents)
        for i, lead_id in enumerate(lead_ids):
            db.add(CampaignLead(
                id=uuid.uuid4(),
                campaign_id=campaign_id,
                lead_id=lead_id,
                tenant_id=tenant_id,
                assigned_agent_id=agent_ids[i % len(agent_ids)],
                status="pending",
            ))

        await db.commit()

    await engine.dispose()

    print("\n" + "=" * 60)
    print("SEED COMPLETE — VSynergize")
    print("=" * 60)
    print(f"Tenant ID:  {tenant_id}")
    print(f"Tenant:     VSynergize (vsynergize)")
    print(f"Agents:     {len(agents_data)} agents created (all available)")
    print(f"Supervisor: Niraj Chordia (niraj@vsynergize.com)")
    print(f"IVR Menus:  3 menus (Language Selection + English + Hindi)")
    print(f"Leads:      {len(leads_data)} B2B prospects created")
    print(f"Campaign:   Q2 B2B Pipeline Acceleration ({len(lead_ids)} leads assigned)")
    print(f"\nAgent IDs:")
    for aid, ad in zip(agent_ids, agents_data):
        print(f"  {ad['name']:20s} [{ad['team']:15s}] {aid}")
    print("=" * 60)
    print(f"\nUse this tenant_id for API calls: {tenant_id}")
    print(f"Dashboard: http://localhost:5173?tenant_id={tenant_id}")
    print(f"API Docs:  http://localhost:8000/docs")


if __name__ == "__main__":
    asyncio.run(seed())
