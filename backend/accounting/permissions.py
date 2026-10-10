"""
Per-user menu permissions (User Management) - enforced server-side for
every /api/ request by MenuPermissionMiddleware, so hiding a button in the
browser is never the only protection.

Rules:
- auth-login is public; every other endpoint needs a valid, active user.
- Super Admin passes every check.
- Shared lookups (customers, ledgers, voucher types, ticket lists, ...)
  are read by several screens, so a plain GET only needs a signed-in user.
- Each write (create / update / delete) and each report's own data
  endpoint is listed in RULES with the menu(s) and flag it needs. Writes
  NOT listed in RULES are Super-Admin-only (fail closed).
"""
import json

from django.core import signing
from django.http import JsonResponse
from django.urls import Resolver404, resolve

from . import sp_client

AUTH_TOKEN_SALT = "voyager-auth"
AUTH_TOKEN_MAX_AGE = 12 * 60 * 60

PUBLIC_URL_NAMES = {"auth-login", "seed-database"}
SUPER_ADMIN_ONLY_PREFIX = "user-management/"

# "upsert" = one save endpoint for both: "edit" when the JSON body carries
# an id, "add" otherwise. "a|b" = either flag. A rule passes if ANY listed
# menu has the flag.
LEDGER_SCREENS = ["accounts", "supplier-master"]
LEDGER_DRILLDOWN_REPORTS = ["rep-ledger-book", "rep-trial-balance", "rep-profit-loss", "rep-day-book", "rep-cash-bank-book"]
RULES = {
    # Masters
    "ledger-group-create": ("add", ["groups", "accounts"]),
    "ledger-create": ("add", LEDGER_SCREENS),
    "ledger-update": ("edit", LEDGER_SCREENS),
    "ledger-delete": ("delete", LEDGER_SCREENS),
    "supplier-commission-rule-create": ("add", ["supplier-master"]),
    "supplier-commission-rule-delete": ("delete", ["supplier-master"]),
    "company-master-save": ("upsert", ["company-master"]),
    "company-master-delete": ("delete", ["company-master"]),
    "voucher-type-save": ("upsert", ["voucher-type"]),
    "voucher-type-delete": ("delete", ["voucher-type"]),
    # Its save body never carries an id (rows upsert by field), so add and
    # edit can't be told apart - either flag allows it.
    "master-mapping-save": ("add|edit", ["master-mapping"]),
    "master-mapping-delete": ("delete", ["master-mapping"]),
    "fop-master-save": ("upsert", ["fop-master"]),
    "fop-master-delete": ("delete", ["fop-master"]),
    "pg-master-save": ("upsert", ["pg-master"]),
    "pg-master-delete": ("delete", ["pg-master"]),
    # Transactions > Airline
    "ticket-create": ("add", ["tickets"]),
    "ticket-update": ("edit", ["tickets"]),
    "ticket-jv-preview-draft": ("view", ["tickets"]),
    "reschedule-ticket-create": ("add", ["trans-airline-reschedule"]),
    "reschedule-ticket-update": ("edit", ["trans-airline-reschedule"]),
    "reschedule-jv-preview-draft": ("view", ["trans-airline-reschedule"]),
    "cancellation-ticket-create": ("add", ["trans-airline-cancellation"]),
    "cancellation-ticket-update": ("edit", ["trans-airline-cancellation"]),
    "cancellation-jv-preview-draft": ("view", ["trans-airline-cancellation"]),
    # Reports (their own data endpoints)
    "day-book-report": ("view", ["rep-day-book"]),
    "cash-bank-book-report": ("view", ["rep-cash-bank-book"]),
    "trial-balance-report": ("view", ["rep-trial-balance"]),
    "profit-loss-report": ("view", ["rep-profit-loss"]),
    "balance-sheet-report": ("view", ["rep-balance-sheet"]),
    "ledger-book-report": ("view", LEDGER_DRILLDOWN_REPORTS),
    "ledger-monthly-summary": ("view", LEDGER_DRILLDOWN_REPORTS),
}

DENIED_MESSAGES = {
    "view": "You don't have access to this screen.",
    "add": "You don't have permission to add new records here.",
    "edit": "You don't have permission to edit records here.",
    "delete": "You don't have permission to delete records here.",
}


def make_token(user_id):
    return signing.dumps({"uid": user_id}, salt=AUTH_TOKEN_SALT)


def user_from_request(request):
    """The active AppUsers row behind this request's Bearer token, or None."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        data = signing.loads(header[7:], salt=AUTH_TOKEN_SALT, max_age=AUTH_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    u = sp_client.app_user_get(data.get("uid"))
    return u if u and u["is_active"] else None


def permissions_for(u):
    """{menu_key: {view, add, edit, delete}} for menus with View ticked; {} for a Super Admin (bypasses checks)."""
    if u["is_super_admin"]:
        return {}
    return {
        r["menu_key"]: {
            "view": bool(r["can_view"]), "add": bool(r["can_add"]),
            "edit": bool(r["can_edit"]), "delete": bool(r["can_delete"]),
        }
        for r in sp_client.user_menu_access_get(u["id"]) if r["can_view"]
    }


def _body_has_id(request):
    try:
        return bool(json.loads(request.body or b"{}").get("id"))
    except (ValueError, AttributeError):
        return False


class MenuPermissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        denied = self._check(request)
        return denied if denied is not None else self.get_response(request)

    def _check(self, request):
        if request.method == "OPTIONS" or not request.path_info.startswith("/api/"):
            return None
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return None
        if match.url_name in PUBLIC_URL_NAMES:
            return None

        u = user_from_request(request)
        if not u:
            return JsonResponse({"error": "Your session has ended. Please sign in again."}, status=401)
        request.app_user = u
        if u["is_super_admin"]:
            return None

        if request.path_info[len("/api/"):].startswith(SUPER_ADMIN_ONLY_PREFIX):
            return JsonResponse({"error": "Only a Super Admin can manage users."}, status=403)

        rule = RULES.get(match.url_name)
        if rule is None:
            if request.method == "GET":
                return None
            return JsonResponse({"error": "You don't have permission to do this."}, status=403)

        action, menu_keys = rule
        if action == "upsert":
            action = "edit" if _body_has_id(request) else "add"
        actions = action.split("|")
        perms = permissions_for(u)
        if any(perms.get(k, {}).get(a) for k in menu_keys for a in actions):
            return None
        return JsonResponse({"error": DENIED_MESSAGES[actions[-1]]}, status=403)
