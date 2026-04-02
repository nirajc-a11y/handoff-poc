"""Create Plivo endpoints (SIP softphone accounts) for VSynergize agents.

Reuses the existing Handoff_POC application. Creates endpoints only if they
don't already exist.

Usage:
    python -m scripts.setup_plivo_vsynergize
"""

import plivo

from app.config import settings


AGENTS = [
    {"username": "priyaagent", "password": "Priya12345", "alias": "PriyaSharma"},
    {"username": "rahulagent", "password": "Rahul12345", "alias": "RahulMehta"},
    {"username": "snehaagent", "password": "Sneha12345", "alias": "SnehaPatil"},
    {"username": "amitagent", "password": "Amit12345", "alias": "AmitDeshmukh"},
    {"username": "nehaagent", "password": "Neha12345", "alias": "NehaKulkarni"},
    {"username": "vikramagent", "password": "Vikram12345", "alias": "VikramJoshi"},
]


def find_or_create_app(client: plivo.RestClient) -> str | None:
    """Find existing Handoff_POC app or create one."""
    base = settings.base_webhook_url.rstrip("/") if settings.base_webhook_url else ""
    if not base:
        base = "https://example.com"
        print("NOTE: BASE_WEBHOOK_URL not set. Using placeholder URLs.")
        print("      Update the application URLs after starting ngrok.\n")

    # Try to find existing app first
    try:
        response = client.applications.list(limit=20)
        app_list = response[0] if isinstance(response, tuple) else response
        items = app_list.objects if hasattr(app_list, "objects") else app_list
        for app_obj in items:
            if getattr(app_obj, "app_name", "") == "Handoff_POC":
                app_id = getattr(app_obj, "app_id", None)
                print(f"Found existing Plivo app: {app_id}")
                return app_id
    except Exception:
        pass

    # Create new app
    print("Creating Plivo Application...")
    try:
        resp = client.applications.create(
            app_name="Handoff_POC",
            answer_url=f"{base}/api/v1/plivo/answer",
            answer_method="POST",
            fallback_answer_url=f"{base}/api/v1/plivo/fallback",
            fallback_method="POST",
            hangup_url=f"{base}/api/v1/plivo/call-status",
            hangup_method="POST",
        )
        app_id = resp["app_id"]
        print(f"Created Plivo app: {app_id}")
        return app_id
    except Exception as e:
        print(f"Failed to create application: {e}")
        return None


def main():
    if not settings.plivo_auth_id or not settings.plivo_auth_token:
        print("ERROR: Set PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN in .env first")
        return

    client = plivo.RestClient(settings.plivo_auth_id, settings.plivo_auth_token)

    app_id = find_or_create_app(client)
    if not app_id:
        print("Could not find or create Plivo application. Exiting.")
        return

    # Create endpoints
    print("\nCreating VSynergize Agent Endpoints...")
    created = 0
    for agent in AGENTS:
        try:
            resp = client.endpoints.create(
                username=agent["username"],
                password=agent["password"],
                alias=agent["alias"],
                app_id=app_id,
            )
            print(f"  Created: {agent['username']} (ID: {resp['endpoint_id']})")
            created += 1
        except plivo.exceptions.PlivoRestError as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                print(f"  Already exists: {agent['username']}")
            else:
                print(f"  Failed: {agent['username']} — {e}")

    # Fetch all endpoints to get the full usernames (Plivo appends a random suffix)
    # Keep only the latest endpoint per alias, delete older duplicates
    print("\nFetching full endpoint usernames from Plivo...")
    alias_to_password = {a["alias"]: a["password"] for a in AGENTS}
    # Collect all matching endpoints grouped by alias
    alias_endpoints: dict[str, list[dict]] = {}
    try:
        response = client.endpoints.list(limit=20)
        ep_list = response[0] if isinstance(response, tuple) else response
        items = ep_list.objects if hasattr(ep_list, "objects") else ep_list
        for ep in items:
            alias = getattr(ep, "alias", "")
            if alias in alias_to_password:
                alias_endpoints.setdefault(alias, []).append({
                    "alias": alias,
                    "username": getattr(ep, "username", "?"),
                    "endpoint_id": getattr(ep, "endpoint_id", "?"),
                    "password": alias_to_password[alias],
                })
    except Exception as e:
        print(f"  Could not list endpoints: {e}")

    # Keep latest (last in list) per alias, delete duplicates
    endpoint_credentials = []
    for alias, eps in alias_endpoints.items():
        # Keep the last one (most recently created), delete the rest
        keep = eps[-1]
        endpoint_credentials.append(keep)
        for dup in eps[:-1]:
            try:
                client.endpoints.delete(dup["endpoint_id"])
                print(f"  Deleted duplicate: {dup['username']} (ID: {dup['endpoint_id']})")
            except Exception as e:
                print(f"  Could not delete {dup['username']}: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("VSYNERGIZE ENDPOINT SETUP COMPLETE")
    print("=" * 60)
    print(f"Application ID: {app_id}")
    print(f"Endpoints created: {created}/{len(AGENTS)}")
    if endpoint_credentials:
        print(f"\nSoftphone Credentials (use FULL username to log in):")
        for cred in endpoint_credentials:
            print(f"  {cred['alias']:18s}  user: {cred['username']}")
            print(f"  {' ':18s}  pass: {cred['password']}")
    else:
        print("\nCould not fetch full usernames. Check Plivo console for the full endpoint usernames.")
    print("\n" + "=" * 60)
    print("IMPORTANT: Plivo appends a random suffix to usernames.")
    print("Use the FULL username shown above (not the short alias) to log in.")
    print("=" * 60)


if __name__ == "__main__":
    main()
