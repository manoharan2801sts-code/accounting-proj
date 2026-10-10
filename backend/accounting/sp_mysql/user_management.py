"""
user_management.py — MySQL/TiDB emulation for User Management stored procedures:
- dbo.sp_AppUser
- dbo.sp_MenuMaster
- dbo.sp_UserMenuAccess
"""
import datetime
import json
from django.db import transaction

from . import sp, query, query_one, execute, bits, to_bool_param, error_row


def _p_int(v):
    if v is None or v == "":
        return None
    return int(v)


def _p_str(v, maxlen=None):
    if v is None:
        return None
    s = str(v)
    if maxlen:
        s = s[:maxlen]
    return s


# ===========================================================================
# dbo.sp_AppUser
# ===========================================================================

@sp("dbo.sp_AppUser", "GET_BY_EMAIL")
def app_user_get_by_email(p):
    email = _p_str(p.get("Email"), 200)
    row = query_one("SELECT * FROM AppUsers WHERE LOWER(RTRIM(email)) = LOWER(RTRIM(%s))", [email])
    if row:
        bits(row, "is_super_admin", "is_active")
        return [row]
    return []


@sp("dbo.sp_AppUser", "LIST")
def app_user_list(p):
    uid = _p_int(p.get("Id"))
    sql = """
        SELECT u.*,
               (SELECT COUNT(*) FROM UserMenuAccess uma WHERE uma.user_id = u.id AND uma.can_view = 1) AS menu_count
        FROM AppUsers u
        WHERE (%s IS NULL OR u.id = %s)
        ORDER BY u.full_name
    """
    rows = query(sql, [uid, uid])
    for r in rows:
        bits(r, "is_super_admin", "is_active")
    return rows


@sp("dbo.sp_AppUser", "SAVE")
def app_user_save(p):
    uid = _p_int(p.get("Id"))
    full_name = _p_str(p.get("FullName"), 150)
    email = _p_str(p.get("Email"), 200)
    role = _p_str(p.get("Role"), 50) or "User"
    branch_name = _p_str(p.get("BranchName"), 100)
    is_super_admin = to_bool_param(p.get("IsSuperAdmin"))
    is_super_admin = 0 if is_super_admin is None else int(bool(is_super_admin))
    is_active = to_bool_param(p.get("IsActive"))
    is_active = 1 if is_active is None else int(bool(is_active))
    password_hash = _p_str(p.get("PasswordHash"), 256)

    if not full_name or not full_name.strip():
        return [{"id": None, "status": "Error", "error": "full_name is required"}]
    if not email or not email.strip():
        return [{"id": None, "status": "Error", "error": "email is required"}]
    email = email.strip()
    full_name = full_name.strip()

    # Unique email check
    dup = query_one(
        "SELECT 1 AS x FROM AppUsers WHERE LOWER(RTRIM(email)) = LOWER(RTRIM(%s)) AND (%s IS NULL OR id <> %s)",
        [email, uid, uid]
    )
    if dup:
        return [{"id": None, "status": "Error", "error": f'A user with email "{email}" already exists.'}]

    # Super admin protection
    if uid is not None and (is_super_admin == 0 or is_active == 0):
        is_current_sa = query_one("SELECT is_super_admin FROM AppUsers WHERE id = %s", [uid])
        if is_current_sa and is_current_sa.get("is_super_admin"):
            sa_count = query_one("SELECT COUNT(*) AS c FROM AppUsers WHERE is_super_admin = 1 AND is_active = 1")
            if (sa_count and sa_count["c"] <= 1):
                return [{"id": None, "status": "Error", "error": "At least one active Super Admin must remain."}]

    now = datetime.datetime.now(datetime.timezone.utc)
    was_created = False

    with transaction.atomic():
        if uid is not None and query_one("SELECT 1 AS x FROM AppUsers WHERE id = %s", [uid]):
            sql = """
                UPDATE AppUsers
                SET full_name = %s, email = %s, role = %s, branch_name = %s,
                    is_super_admin = %s, is_active = %s,
                    password_hash = COALESCE(%s, password_hash), updated_at = %s
                WHERE id = %s
            """
            execute(sql, [full_name, email, role, branch_name, is_super_admin, is_active, password_hash, now, uid])
            result_id = uid
        else:
            sql = """
                INSERT INTO AppUsers (full_name, email, role, branch_name, is_super_admin, is_active, password_hash, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            _, result_id = execute(sql, [full_name, email, role, branch_name, is_super_admin, is_active, password_hash, now, now])
            was_created = True

        row = query_one("SELECT * FROM AppUsers WHERE id = %s", [result_id])
        if row:
            bits(row, "is_super_admin", "is_active")
            row["was_created"] = was_created
            row["status"] = "Success"
            return [row]
        return error_row("Could not retrieve saved user.")


@sp("dbo.sp_AppUser", "DELETE")
def app_user_delete(p):
    uid = _p_int(p.get("Id"))
    if uid is None or not query_one("SELECT 1 AS x FROM AppUsers WHERE id = %s", [uid]):
        return [{"id": None, "status": "Error", "error": "User not found."}]

    is_current_sa = query_one("SELECT is_super_admin FROM AppUsers WHERE id = %s", [uid])
    if is_current_sa and is_current_sa.get("is_super_admin"):
        sa_count = query_one("SELECT COUNT(*) AS c FROM AppUsers WHERE is_super_admin = 1 AND is_active = 1")
        if sa_count and sa_count["c"] <= 1:
            return [{"id": None, "status": "Error", "error": "At least one active Super Admin must remain."}]

    with transaction.atomic():
        execute("DELETE FROM UserMenuAccess WHERE user_id = %s", [uid])
        execute("UPDATE UserMenuAccess SET created_by_id = NULL WHERE created_by_id = %s", [uid])
        execute("DELETE FROM AppUsers WHERE id = %s", [uid])

    return [{"id": uid, "status": "Success"}]


# ===========================================================================
# dbo.sp_MenuMaster
# ===========================================================================

@sp("dbo.sp_MenuMaster", "LIST")
def menu_master_list(p):
    rows = query("SELECT * FROM MenuMaster WHERE is_active = 1 ORDER BY module, sort_order")
    for r in rows:
        bits(r, "is_active")
    return rows


# ===========================================================================
# dbo.sp_UserMenuAccess
# ===========================================================================

@sp("dbo.sp_UserMenuAccess", "GET")
def user_menu_access_get(p):
    uid = _p_int(p.get("UserId"))
    if uid is None or not query_one("SELECT 1 AS x FROM AppUsers WHERE id = %s", [uid]):
        return [{"menu_key": None, "status": "Error", "error": "User not found."}]

    sql = """
        SELECT
            mm.menu_key, mm.title, mm.parent_key, mm.module, mm.sort_order,
            COALESCE(uma.can_view, 0) AS can_view,
            COALESCE(uma.can_add, 0) AS can_add,
            COALESCE(uma.can_edit, 0) AS can_edit,
            COALESCE(uma.can_delete, 0) AS can_delete
        FROM MenuMaster mm
        LEFT JOIN UserMenuAccess uma ON uma.menu_key = mm.menu_key AND uma.user_id = %s
        WHERE mm.is_active = 1
        ORDER BY mm.module, mm.sort_order
    """
    rows = query(sql, [uid])
    for r in rows:
        bits(r, "can_view", "can_add", "can_edit", "can_delete")
    return rows


@sp("dbo.sp_UserMenuAccess", "SAVE")
def user_menu_access_save(p):
    uid = _p_int(p.get("UserId"))
    created_by = _p_int(p.get("CreatedBy"))
    access_json = p.get("AccessJson")

    if uid is None or not query_one("SELECT 1 AS x FROM AppUsers WHERE id = %s", [uid]):
        return [{"menu_key": None, "status": "Error", "error": "User not found."}]

    try:
        items = json.loads(access_json) if isinstance(access_json, str) else (access_json or [])
    except Exception as e:
        return [{"menu_key": None, "status": "Error", "error": f"Invalid JSON: {e}"}]

    now = datetime.datetime.now(datetime.timezone.utc)
    with transaction.atomic():
        for item in items:
            menu_key = _p_str(item.get("menu_key"), 60)
            if not menu_key:
                continue
            can_view = 1 if to_bool_param(item.get("can_view")) else 0
            can_add = 1 if to_bool_param(item.get("can_add")) else 0
            can_edit = 1 if to_bool_param(item.get("can_edit")) else 0
            can_delete = 1 if to_bool_param(item.get("can_delete")) else 0

            execute("""
                INSERT INTO UserMenuAccess (user_id, menu_key, can_view, can_add, can_edit, can_delete, created_by_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    can_view = VALUES(can_view),
                    can_add = VALUES(can_add),
                    can_edit = VALUES(can_edit),
                    can_delete = VALUES(can_delete),
                    updated_at = VALUES(updated_at)
            """, [uid, menu_key, can_view, can_add, can_edit, can_delete, created_by, now, now])

    return [{"user_id": uid, "status": "Success"}]
