"""Demo script: walks through all 6 handoff scenarios via API calls.

Usage:
    python -m scripts.demo --tenant-id <TENANT_ID> [--base-url http://localhost:8000]

Run the seed script first to create the demo tenant and data.
"""

import argparse
import asyncio
import sys
import time

import httpx


BASE_URL = "http://localhost:8000"
HEADERS = {}


def h(tenant_id: str, user_id: str = "00000000-0000-0000-0000-000000000000") -> dict:
    return {
        "X-Tenant-Id": tenant_id,
        "X-User-Id": user_id,
        "Content-Type": "application/json",
    }


async def scenario_1_inbound_ivr_to_ai_to_human(client: httpx.AsyncClient, tenant_id: str):
    """Scenario 1: Inbound call -> IVR -> AI -> Human (confidence drop)"""
    print("\n" + "=" * 60)
    print("SCENARIO 1: Inbound Call -> IVR -> AI -> Human (confidence drop)")
    print("=" * 60)

    # 1. Simulate inbound call webhook
    print("\n[1] Inbound call arrives...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/calls/inbound/webhook",
        json={
            "from_number": "+919876543210",
            "to_number": "+918000000001",
            "provider_call_id": f"mock-inbound-{int(time.time())}",
            "customer_name": "John Customer",
        },
        headers=h(tenant_id),
    )
    assert resp.status_code == 200, f"Failed: {resp.text}"
    conv = resp.json()
    conv_id = conv["id"]
    print(f"   Conversation created: {conv_id}")
    print(f"   State: {conv['state']}")

    await asyncio.sleep(1)

    # 2. Simulate answer -> enters IVR
    print("\n[2] Call answered, entering IVR...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/calls/{conv_id}/answer",
        headers=h(tenant_id),
    )
    if resp.status_code == 200:
        conv = resp.json()
        print(f"   State: {conv['state']}, Handler: {conv['current_handler_type']}")
    else:
        print(f"   Answer response: {resp.status_code} - {resp.text}")

    await asyncio.sleep(1)

    # 3. Customer presses 1 (AI handoff)
    print("\n[3] Customer presses 1 (Sales -> AI handoff)...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/calls/{conv_id}/dtmf",
        json={"digit": "1"},
        headers=h(tenant_id),
    )
    if resp.status_code == 200:
        conv = resp.json()
        print(f"   State: {conv['state']}, Handler: {conv['current_handler_type']}")
    else:
        print(f"   DTMF response: {resp.status_code} - {resp.text}")

    await asyncio.sleep(1)

    # 4. AI handles, then escalate to human
    print("\n[4] AI confidence drops, escalating to human...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/handoffs/escalate",
        json={"conversation_id": conv_id, "reason": "AI confidence below threshold (0.42)"},
        headers=h(tenant_id),
    )
    if resp.status_code == 200:
        conv = resp.json()
        print(f"   State: {conv['state']}, Handler: {conv['current_handler_type']}")
    else:
        print(f"   Escalation response: {resp.status_code} - {resp.text}")

    await asyncio.sleep(1)

    # 5. Check final state
    print("\n[5] Checking conversation state...")
    resp = await client.get(f"{BASE_URL}/api/v1/conversations/{conv_id}", headers=h(tenant_id))
    conv = resp.json()
    print(f"   State: {conv['state']}")
    print(f"   Handler: {conv['current_handler_type']} (ID: {conv.get('current_handler_id', 'N/A')})")

    # 6. View handoff history
    resp = await client.get(f"{BASE_URL}/api/v1/conversations/{conv_id}/handoffs", headers=h(tenant_id))
    handoffs = resp.json()
    print(f"\n   Handoff Events ({len(handoffs)}):")
    for he in handoffs:
        print(f"   - {he['event_type']}: {he.get('from_state', '?')} -> {he.get('to_state', '?')} ({he.get('reason', '')})")

    return conv_id


async def scenario_2_inbound_ivr_skip_to_human(client: httpx.AsyncClient, tenant_id: str):
    """Scenario 2: Inbound call -> IVR -> Press 0 -> Skip to human"""
    print("\n" + "=" * 60)
    print("SCENARIO 2: Inbound Call -> IVR -> Press 0 -> Direct to Human")
    print("=" * 60)

    print("\n[1] Inbound call arrives...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/calls/inbound/webhook",
        json={
            "from_number": "+919876543211",
            "to_number": "+918000000001",
            "provider_call_id": f"mock-inbound-skip-{int(time.time())}",
            "customer_name": "Jane Prospect",
        },
        headers=h(tenant_id),
    )
    conv = resp.json()
    conv_id = conv["id"]
    print(f"   Conversation: {conv_id}, State: {conv['state']}")

    await asyncio.sleep(0.5)

    print("\n[2] Call answered, entering IVR...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/calls/{conv_id}/answer",
        headers=h(tenant_id),
    )
    if resp.status_code == 200:
        conv = resp.json()
        print(f"   State: {conv['state']}, Handler: {conv['current_handler_type']}")
    else:
        print(f"   Answer response: {resp.status_code} - {resp.text}")

    await asyncio.sleep(0.5)

    print("\n[3] Customer presses 0 (skip to human)...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/handoffs/ivr-skip",
        json={"conversation_id": conv_id},
        headers=h(tenant_id),
    )
    if resp.status_code == 200:
        conv = resp.json()
        print(f"   State: {conv['state']}, Handler: {conv['current_handler_type']}")
    else:
        print(f"   Response: {resp.status_code} - {resp.text}")


async def scenario_3_human_to_human_transfer(client: httpx.AsyncClient, tenant_id: str, conv_id: str):
    """Scenario 3: Human -> Human warm transfer"""
    print("\n" + "=" * 60)
    print("SCENARIO 3: Human -> Human Warm Transfer")
    print("=" * 60)

    # Refetch conversation to get actual state (may have been auto-assigned)
    resp = await client.get(f"{BASE_URL}/api/v1/conversations/{conv_id}", headers=h(tenant_id))
    conv = resp.json()
    print(f"\n[0] Current state: {conv['state']}, Handler: {conv['current_handler_type']} (ID: {conv.get('current_handler_id', 'N/A')})")

    if conv["state"] != "human_handling":
        print("   Conversation not in human_handling state. Skipping transfer demo.")
        return

    # Get available agents (need one different from current handler)
    resp = await client.get(f"{BASE_URL}/api/v1/agents/available", headers=h(tenant_id))
    agents = resp.json()
    if len(agents) < 1:
        print("   No available agents for transfer target. Skipping.")
        return

    target_agent_id = agents[0]["id"]
    print(f"\n[1] Warm transferring to agent: {agents[0].get('name', target_agent_id)}...")

    resp = await client.post(
        f"{BASE_URL}/api/v1/handoffs/transfer",
        json={"conversation_id": conv_id, "target_agent_id": target_agent_id, "warm": True},
        headers=h(tenant_id),
    )
    if resp.status_code == 200:
        conv = resp.json()
        print(f"   State: {conv['state']}, Handler: {conv['current_handler_type']}")
    else:
        print(f"   Transfer response: {resp.status_code} - {resp.text}")


async def scenario_4_outbound_campaign_call(client: httpx.AsyncClient, tenant_id: str):
    """Scenario 4: Outbound campaign call"""
    print("\n" + "=" * 60)
    print("SCENARIO 4: Outbound Campaign Call")
    print("=" * 60)

    # Get campaigns
    resp = await client.get(f"{BASE_URL}/api/v1/campaigns", headers=h(tenant_id))
    campaigns = resp.json()
    if not campaigns:
        print("   No campaigns found. Skipping.")
        return

    # Get an agent's user_id for the X-User-Id header
    resp = await client.get(f"{BASE_URL}/api/v1/agents", headers=h(tenant_id))
    agents = resp.json()
    agent_user_id = agents[0].get("user_id", "00000000-0000-0000-0000-000000000000") if agents else "00000000-0000-0000-0000-000000000000"

    campaign_id = campaigns[0]["id"]
    print(f"\n[1] Auto-dialing next lead from campaign '{campaigns[0]['name']}'...")

    resp = await client.post(
        f"{BASE_URL}/api/v1/calls/outbound/campaign",
        json={"campaign_id": campaign_id},
        headers=h(tenant_id, user_id=agent_user_id),
    )
    if resp.status_code == 200:
        conv = resp.json()
        print(f"   Conversation: {conv['id']}, State: {conv['state']}")
        print(f"   Customer: {conv.get('customer_identifier', 'N/A')}")
    else:
        print(f"   Response: {resp.status_code} - {resp.text}")


async def scenario_5_whatsapp_with_ai(client: httpx.AsyncClient, tenant_id: str):
    """Scenario 5: WhatsApp inbound -> AI handling"""
    print("\n" + "=" * 60)
    print("SCENARIO 5: WhatsApp Inbound -> AI Handling")
    print("=" * 60)

    print("\n[1] Inbound WhatsApp message...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/channels/whatsapp/webhook",
        json={
            "from_number": "+919876543215",
            "content": "Hi, I need help with my billing issue",
            "tenant_id": tenant_id,
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"   Conversation: {data.get('conversation_id', 'N/A')}")
        print(f"   AI Response: {data.get('ai_response', 'N/A')}")
    else:
        print(f"   Response: {resp.status_code} - {resp.text}")

    await asyncio.sleep(1)

    print("\n[2] Customer asks for human agent...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/channels/whatsapp/webhook",
        json={
            "from_number": "+919876543215",
            "content": "I want to speak to a human agent please",
            "tenant_id": tenant_id,
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"   Escalation triggered: {data.get('escalated', 'N/A')}")
    else:
        print(f"   Response: {resp.status_code} - {resp.text}")


async def scenario_6_email_thread(client: httpx.AsyncClient, tenant_id: str):
    """Scenario 6: Email inbound with threading"""
    print("\n" + "=" * 60)
    print("SCENARIO 6: Email Inbound with Threading")
    print("=" * 60)

    print("\n[1] Inbound email arrives...")
    resp = await client.post(
        f"{BASE_URL}/api/v1/channels/email/webhook",
        json={
            "from_address": "customer@example.com",
            "to_address": "support@demo.com",
            "subject": "Issue with my order #12345",
            "body_html": "<p>Hello, I have an issue with my recent order. The tracking shows delivered but I haven't received it.</p>",
            "body_text": "Hello, I have an issue with my recent order.",
            "tenant_id": tenant_id,
            "message_id": f"<msg-{int(time.time())}@example.com>",
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"   Conversation: {data.get('conversation_id', 'N/A')}")
    else:
        print(f"   Response: {resp.status_code} - {resp.text}")


async def show_dashboard_state(client: httpx.AsyncClient, tenant_id: str):
    """Show final dashboard state."""
    print("\n" + "=" * 60)
    print("FINAL DASHBOARD STATE")
    print("=" * 60)

    # Active conversations
    resp = await client.get(f"{BASE_URL}/api/v1/conversations/active", headers=h(tenant_id))
    convs = resp.json()
    print(f"\nActive Conversations: {len(convs)}")
    for c in convs:
        print(f"  - {c['channel']} | {c['state']} | {c['customer_identifier']} | handler={c['current_handler_type']}")

    # Agent statuses
    resp = await client.get(f"{BASE_URL}/api/v1/agents", headers=h(tenant_id))
    agents = resp.json()
    print(f"\nAgents ({len(agents)}):")
    for a in agents:
        status = a.get("status", {})
        print(f"  - {a.get('name', a['id'])} | {status.get('status', '?')} | convs={status.get('current_conversations', 0)}")

    # Queue
    resp = await client.get(f"{BASE_URL}/api/v1/handoffs/queue/stats", headers=h(tenant_id))
    stats = resp.json()
    print(f"\nQueue Stats: {stats}")


async def main():
    parser = argparse.ArgumentParser(description="Handoff POC Demo")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID from seed script")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url

    async with httpx.AsyncClient(timeout=30.0) as client:
        print("\nHandoff POC - Demo Script")
        print(f"Tenant: {args.tenant_id}")
        print(f"API: {BASE_URL}")
        print(f"Dashboard: {BASE_URL}/static/index.html?tenant_id={args.tenant_id}")

        # Run all scenarios
        conv_id = await scenario_1_inbound_ivr_to_ai_to_human(client, args.tenant_id)
        await asyncio.sleep(2)

        await scenario_2_inbound_ivr_skip_to_human(client, args.tenant_id)
        await asyncio.sleep(2)

        if conv_id:
            await scenario_3_human_to_human_transfer(client, args.tenant_id, conv_id)
        await asyncio.sleep(2)

        await scenario_4_outbound_campaign_call(client, args.tenant_id)
        await asyncio.sleep(2)

        await scenario_5_whatsapp_with_ai(client, args.tenant_id)
        await asyncio.sleep(2)

        await scenario_6_email_thread(client, args.tenant_id)
        await asyncio.sleep(2)

        await show_dashboard_state(client, args.tenant_id)

        print("\n" + "=" * 60)
        print("DEMO COMPLETE")
        print("=" * 60)
        print(f"\nOpen the live dashboard to see all events:")
        print(f"  {BASE_URL}/static/index.html?tenant_id={args.tenant_id}")


if __name__ == "__main__":
    asyncio.run(main())
