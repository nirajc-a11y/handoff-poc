"""Seed script: creates demo tenant, agents, IVR menus, campaign with leads."""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.db.models import *  # noqa: F401, F403


async def seed():
    engine = create_async_engine(settings.database_url, echo=True)

    # Create all tables (for dev, skip alembic)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # Clean existing data
        await db.execute(delete(HandoffEvent))
        await db.execute(delete(Message))
        await db.execute(delete(ChannelSession))
        await db.execute(delete(SupportTicket))
        await db.execute(delete(Conversation))
        await db.execute(delete(CampaignLead))
        await db.execute(delete(Campaign))
        await db.execute(delete(IVRMenuOption))
        await db.execute(delete(IVRMenu))
        await db.execute(delete(AgentStatus))
        await db.execute(delete(AgentProfile))
        await db.execute(delete(User))
        await db.execute(delete(Lead))
        await db.execute(delete(Tenant))
        await db.commit()
        print("Cleaned existing data")

        # --- Tenant ---
        tenant_id = uuid.uuid4()
        tenant = Tenant(
            id=tenant_id,
            name="Demo Corp",
            slug="demo-corp",
            status="active",
            config={
                "providers": {"telephony": "twilio"},
                "telephony_provider": "twilio",
                "ai_confidence_threshold": 0.7,
                "default_language": "en",
                "supported_languages": ["en", "mr"],
                "groq_model": "llama-3.3-70b-versatile",
                "ai_system_prompt": "You are a helpful customer support agent for Demo Corp.",
            },
        )
        db.add(tenant)
        await db.flush()  # Ensure tenant exists before FK-dependent inserts

        # --- Users + Agent Profiles + Statuses ---
        agents_data = [
            {"name": "Alice Johnson", "email": "alice@demo.com", "team": "support", "skills": ["billing", "technical"]},
            {"name": "Bob Smith", "email": "bob@demo.com", "team": "support", "skills": ["technical", "networking"]},
            {"name": "Carol Davis", "email": "carol@demo.com", "team": "sales", "skills": ["sales", "retention"]},
            {"name": "Dave Wilson", "email": "dave@demo.com", "team": "sales", "skills": ["sales", "upsell"]},
            {"name": "Eve Martinez", "email": "eve@demo.com", "team": "support", "skills": ["billing", "complaints"]},
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

        # --- Supervisor ---
        supervisor = User(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email="supervisor@demo.com",
            name="Sarah Supervisor",
            role="supervisor",
        )
        db.add(supervisor)
        await db.flush()  # Ensure users/agents exist before dependent inserts

        # --- IVR Menus (Bilingual: English + Marathi) ---

        # Pre-generate IDs so they can be cross-referenced
        en_menu_id = uuid.uuid4()
        mr_menu_id = uuid.uuid4()

        # Root menu: Language selection
        lang_menu_id = uuid.uuid4()
        lang_menu = IVRMenu(
            id=lang_menu_id,
            tenant_id=tenant_id,
            name="Language Selection",
            is_root=True,
            welcome_message=(
                "Thank you for calling Demo Corp. Your call is important to us. "
                "For English, press 1. "
                "Demo Corp मध्ये कॉल केल्याबद्दल धन्यवाद. मराठीसाठी, 2 दाबा."
            ),
            config={"timeout": 10, "retries": 3},
        )
        db.add(lang_menu)

        # Language menu options
        db.add(IVRMenuOption(
            id=uuid.uuid4(), menu_id=lang_menu_id, tenant_id=tenant_id,
            digit="1", label="English", action_type="submenu",
            target_id=en_menu_id,
            target_config={"language": "en"},
            sort_order=0,
        ))
        db.add(IVRMenuOption(
            id=uuid.uuid4(), menu_id=lang_menu_id, tenant_id=tenant_id,
            digit="2", label="Marathi", action_type="submenu",
            target_id=mr_menu_id,
            target_config={"language": "mr"},
            sort_order=1,
        ))

        # English Main Menu
        en_menu = IVRMenu(
            id=en_menu_id,
            tenant_id=tenant_id,
            name="English Main Menu",
            is_root=False,
            welcome_message=(
                "Please listen carefully as our menu options have changed. "
                "To explore our products and speak with sales, press 1. "
                "For technical support, press 2. "
                "For billing and account enquiries, press 3. "
                "To speak directly with a customer service representative, press 0. "
                "To hear these options again, press hash."
            ),
            config={"timeout": 12, "retries": 3},
        )
        db.add(en_menu)

        # English options
        for digit, label, action, config in [
            ("1", "Sales", "ai_handoff", {
                "queue_name": "sales", "skill_requirements": ["sales"], "language": "en",
                "greeting": (
                    "Welcome to Demo Corp Sales. I'm your AI sales assistant. "
                    "I can help you with product information, pricing, plans, and new subscriptions. "
                    "How may I assist you today?"
                ),
            }),
            ("2", "Technical Support", "ai_handoff", {
                "queue_name": "support", "skill_requirements": ["technical"], "language": "en",
                "greeting": (
                    "You've reached Demo Corp Technical Support. I'm your AI support assistant. "
                    "I can help troubleshoot issues, guide you through setup, and answer technical questions. "
                    "Please describe the issue you're experiencing."
                ),
            }),
            ("3", "Billing", "ai_handoff", {
                "queue_name": "billing", "skill_requirements": ["billing"], "language": "en",
                "greeting": (
                    "Welcome to Demo Corp Billing. I'm your AI billing assistant. "
                    "I can help with invoices, payments, plan changes, and account enquiries. "
                    "What would you like help with?"
                ),
            }),
            ("0", "Speak to an agent", "human_queue", {"queue_name": "general", "language": "en"}),
            ("#", "Repeat menu", "play_message", {"message": "Let me repeat the menu options for you.", "language": "en"}),
        ]:
            db.add(IVRMenuOption(
                id=uuid.uuid4(), menu_id=en_menu_id, tenant_id=tenant_id,
                digit=digit, label=label, action_type=action,
                target_config=config, sort_order=int(digit) if digit.isdigit() else 9,
            ))

        # Marathi Main Menu
        mr_menu = IVRMenu(
            id=mr_menu_id,
            tenant_id=tenant_id,
            name="Marathi Main Menu",
            is_root=False,
            welcome_message=(
                "कृपया आमचे पर्याय काळजीपूर्वक ऐका. "
                "आमच्या उत्पादनांबद्दल जाणून घेण्यासाठी आणि विक्री विभागाशी बोलण्यासाठी, 1 दाबा. "
                "तांत्रिक सहाय्यासाठी, 2 दाबा. "
                "बिलिंग आणि खाते चौकशीसाठी, 3 दाबा. "
                "ग्राहक सेवा प्रतिनिधीशी थेट बोलण्यासाठी, 0 दाबा. "
                "हे पर्याय पुन्हा ऐकण्यासाठी, हॅश दाबा."
            ),
            config={"timeout": 12, "retries": 3},
        )
        db.add(mr_menu)

        # Marathi options
        for digit, label, action, config in [
            ("1", "विक्री", "ai_handoff", {
                "queue_name": "sales", "skill_requirements": ["sales"], "language": "mr",
                "greeting": (
                    "Demo Corp विक्री विभागात आपले स्वागत आहे. मी तुमचा AI विक्री सहाय्यक आहे. "
                    "मी तुम्हाला उत्पादन माहिती, किंमत, योजना आणि नवीन सदस्यत्वाबद्दल मदत करू शकतो. "
                    "मी तुम्हाला कशी मदत करू शकतो?"
                ),
            }),
            ("2", "तांत्रिक सहाय्य", "ai_handoff", {
                "queue_name": "support", "skill_requirements": ["technical"], "language": "mr",
                "greeting": (
                    "Demo Corp तांत्रिक सहाय्यता विभागात आपले स्वागत आहे. मी तुमचा AI सहाय्यक आहे. "
                    "मी समस्या निवारण, सेटअप मार्गदर्शन आणि तांत्रिक प्रश्नांमध्ये मदत करू शकतो. "
                    "कृपया तुम्हाला कोणती समस्या आहे ते सांगा."
                ),
            }),
            ("3", "बिलिंग", "ai_handoff", {
                "queue_name": "billing", "skill_requirements": ["billing"], "language": "mr",
                "greeting": (
                    "Demo Corp बिलिंग विभागात आपले स्वागत आहे. मी तुमचा AI बिलिंग सहाय्यक आहे. "
                    "मी चलन, पेमेंट, योजना बदल आणि खाते चौकशीमध्ये मदत करू शकतो. "
                    "तुम्हाला कशाबद्दल मदत हवी आहे?"
                ),
            }),
            ("0", "एजंटशी बोला", "human_queue", {"queue_name": "general", "language": "mr"}),
            ("#", "मेनू पुन्हा ऐका", "play_message", {"message": "मी तुम्हाला मेनू पर्याय पुन्हा सांगतो.", "language": "mr"}),
        ]:
            db.add(IVRMenuOption(
                id=uuid.uuid4(), menu_id=mr_menu_id, tenant_id=tenant_id,
                digit=digit, label=label, action_type=action,
                target_config=config, sort_order=int(digit) if digit.isdigit() else 9,
            ))

        # --- Leads ---
        leads_data = [
            {"name": "John Customer", "phone": "+919876543210", "email": "john@example.com", "whatsapp_number": "+919876543210"},
            {"name": "Jane Prospect", "phone": "+919876543211", "email": "jane@example.com", "whatsapp_number": "+919876543211"},
            {"name": "Mike Lead", "phone": "+919876543212", "email": "mike@example.com", "whatsapp_number": "+919876543212"},
            {"name": "Sarah Interest", "phone": "+919876543213", "email": "sarah@example.com", "whatsapp_number": "+919876543213"},
            {"name": "Tom Buyer", "phone": "+919876543214", "email": "tom@example.com", "whatsapp_number": "+919876543214"},
            {"name": "Lisa Contact", "phone": "+919876543215", "email": "lisa@example.com", "whatsapp_number": "+919876543215"},
            {"name": "Chris Lead", "phone": "+919876543216", "email": "chris@example.com", "whatsapp_number": "+919876543216"},
            {"name": "Amy Target", "phone": "+919876543217", "email": "amy@example.com", "whatsapp_number": "+919876543217"},
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
                metadata_={"source": "seed_script"},
            ))
            lead_ids.append(lead_id)

        await db.flush()  # Ensure leads exist before campaign_leads

        # --- Campaign ---
        campaign_id = uuid.uuid4()
        campaign = Campaign(
            id=campaign_id,
            tenant_id=tenant_id,
            name="Q2 Outbound Sales",
            status="active",
            type="outbound_call",
            config={"dial_mode": "preview", "max_retries": 3, "retry_delay_minutes": 30},
        )
        db.add(campaign)
        await db.flush()  # Ensure campaign exists before campaign_leads

        # Assign leads to campaign
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
    print("SEED COMPLETE")
    print("=" * 60)
    print(f"Tenant ID:  {tenant_id}")
    print(f"Tenant:     Demo Corp (demo-corp)")
    print(f"Agents:     {len(agents_data)} agents created (all available)")
    print(f"IVR Menus:  3 menus (Language Selection + English + Marathi)")
    print(f"Leads:      {len(leads_data)} leads created")
    print(f"Campaign:   Q2 Outbound Sales ({len(lead_ids)} leads assigned)")
    print(f"\nAgent IDs:")
    for i, (aid, ad) in enumerate(zip(agent_ids, agents_data)):
        print(f"  {ad['name']}: {aid}")
    print("=" * 60)
    print(f"\nUse this tenant_id for API calls: {tenant_id}")
    print(f"Dashboard URL: http://localhost:8000/static/index.html?tenant_id={tenant_id}")


if __name__ == "__main__":
    asyncio.run(seed())
