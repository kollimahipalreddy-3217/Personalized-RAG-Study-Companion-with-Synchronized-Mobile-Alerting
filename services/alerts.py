# ============================================================
#  alerts.py — Web Push Notification Dispatcher
#  Personalized RAG Study Companion with Synchronized Mobile Alerting
#  Application Interface: StudyEdge AI
# ============================================================

import json, os
from pywebpush import webpush, WebPushException

# ─────────────────────────────────────────
#  Load VAPID keys
# ─────────────────────────────────────────
VAPID_PRIVATE_KEY = "vapid_private.pem"
VAPID_PUBLIC_KEY  = ""
VAPID_CLAIMS      = {"sub": "mailto:admin@studyedge.local"}

try:
    if os.path.exists("vapid_config.json"):
        with open("vapid_config.json") as f:
            VAPID_PUBLIC_KEY = json.load(f).get("VAPID_PUBLIC_KEY", "")
except Exception as e:
    print(f"[ALERTS] Could not load VAPID config: {e}")


def send_push_notification(subscription_json: str, title: str, body: str,
                            icon: str = "/static/icon-192.png"):
    """
    Send a Web Push Notification.

    Works even when:
    - The phone screen is off
    - The browser is in the background
    - The website tab is closed
    - The browser is minimized

    Args:
        subscription_json: JSON string of the browser push subscription object
        title: Notification title
        body: Notification message body
        icon: URL of icon to show in the notification
    """
    if not VAPID_PRIVATE_KEY or not os.path.exists(VAPID_PRIVATE_KEY):
        print("[ALERTS] VAPID private key not found. Run: python vapid_setup.py")
        return

    try:
        subscription_info = json.loads(subscription_json)
        payload = json.dumps({"title": title, "body": body, "icon": icon})

        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        print(f"[ALERTS] Push sent: '{title}' — {body[:60]}")

    except WebPushException as e:
        print(f"[ALERTS] WebPush failed: {e}")
    except json.JSONDecodeError:
        print("[ALERTS] Invalid subscription JSON.")
    except Exception as e:
        print(f"[ALERTS] Unexpected error: {e}")
