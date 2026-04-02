"""Create Plivo endpoints (agent softphone accounts) and an Application via API.

Usage:
    python -m scripts.setup_plivo
"""

import plivo

from app.config import settings


def main():
    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        print("ERROR: Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env first")
        return

    client = plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)

    # --- Create Application ---
    # Plivo requires real URLs (not localhost) for answer/hangup.
    # Use a placeholder — you'll update these once ngrok is running.
    base = settings.base_webhook_url.rstrip("/") if settings.base_webhook_url else ""
    if not base:
        # Use a dummy URL so we can create the app; update later with ngrok URL
        base = "https://example.com"
        print("NOTE: BASE_WEBHOOK_URL not set. Using placeholder URLs.")
        print("      Update the application URLs after starting ngrok.\n")

    print("Creating Plivo Application...")
    app_id = None
    try:
        app_response = client.applications.create(
            app_name="Handoff_POC",
            answer_url=f"{base}/api/v1/plivo/answer",
            answer_method="POST",
            fallback_answer_url=f"{base}/api/v1/plivo/fallback",
            fallback_method="POST",
            hangup_url=f"{base}/api/v1/plivo/call-status",
            hangup_method="POST",
        )
        app_id = app_response["app_id"]
        print(f"  Application created: {app_id}")
    except Exception as e:
        print(f"  Application creation failed: {e}")
        # Try to find existing app
        try:
            response = client.applications.list(limit=20)
            app_list = response[0] if isinstance(response, tuple) else response
            items = app_list.objects if hasattr(app_list, 'objects') else app_list
            for app_obj in items:
                name = getattr(app_obj, 'app_name', '')
                if name == "Handoff_POC":
                    app_id = getattr(app_obj, 'app_id', None)
                    print(f"  Found existing app: {app_id}")
                    break
        except Exception as ex:
            print(f"  Error listing apps: {ex}")
        if not app_id:
            print("  Could not find or create application. Exiting.")
            return

    # --- Create Endpoints ---
    agents = [
        {"username": "aliceagent", "password": "Alice12345", "alias": "AliceJohnson"},
        {"username": "bobagent", "password": "Bob12345", "alias": "BobSmith"},
        {"username": "carolagent", "password": "Carol12345", "alias": "CarolDavis"},
    ]

    print("\nCreating Agent Endpoints...")
    for agent in agents:
        try:
            resp = client.endpoints.create(
                username=agent["username"],
                password=agent["password"],
                alias=agent["alias"],
                app_id=app_id,
            )
            print(f"  Created: {agent['username']} (ID: {resp['endpoint_id']})")
        except plivo.exceptions.PlivoRestError as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print(f"  Already exists: {agent['username']}")
            else:
                print(f"  Failed to create {agent['username']}: {e}")

    # --- List all endpoints ---
    print("\nAll Endpoints:")
    try:
        response = client.endpoints.list(limit=20)
        endpoint_list = response[0] if isinstance(response, tuple) else response
        if hasattr(endpoint_list, 'objects'):
            for ep in endpoint_list.objects:
                print(f"  - {ep.username} | Alias: {ep.alias} | ID: {ep.endpoint_id}")
        elif hasattr(endpoint_list, '__iter__'):
            for ep in endpoint_list:
                print(f"  - {getattr(ep, 'username', '?')} | Alias: {getattr(ep, 'alias', '?')} | ID: {getattr(ep, 'endpoint_id', '?')}")
        else:
            print(f"  Response: {endpoint_list}")
    except Exception as e:
        print(f"  Could not list endpoints: {e}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print(f"Application ID: {app_id}")
    print(f"\nAgent Softphone Credentials:")
    for agent in agents:
        print(f"  Username: {agent['username']}")
        print(f"  Password: {agent['password']}")
        print()
    print("Use these to log in to the softphone on the dashboard.")
    print(f"\nIf you buy a phone number, attach Application '{app_id}' to it.")
    print("=" * 60)


if __name__ == "__main__":
    main()
