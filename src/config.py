"""Gestión de cuentas de email para ingesta de tickets de Mercadona.
Almacena cuentas en JSON con contraseñas cifradas base64 (no es seguridad
fuerte, pero evita que estén en texto plano en el archivo)."""
import json
import base64
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).parent.parent
CONFIG_FILE = BASE_DIR / "data" / "email_accounts.json"


def _encode(password: str) -> str:
    return base64.b64encode(password.encode()).decode()


def _decode(encoded: str) -> str:
    return base64.b64decode(encoded.encode()).decode()


def load_accounts() -> List[dict]:
    """Carga las cuentas configuradas. Devuelve lista sin las contraseñas."""
    if not CONFIG_FILE.exists():
        return []
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)
    # No devolver la contraseña en texto plano
    return [{"email": a["email"], "imap_host": a["imap_host"],
             "imap_port": a.get("imap_port", 993),
             "label": a.get("label", a["email"])} for a in accounts]


def load_accounts_full() -> List[dict]:
    """Carga las cuentas con contraseñas descifradas (uso interno)."""
    if not CONFIG_FILE.exists():
        return []
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)
    for a in accounts:
        a["password"] = _decode(a["password_enc"])
    return accounts


def add_account(email: str, password: str, label: str = "",
                imap_host: str = "imap.gmail.com", imap_port: int = 993) -> bool:
    """Añade una nueva cuenta. Devuelve False si ya existe."""
    accounts = load_accounts_full()
    for a in accounts:
        if a["email"] == email:
            return False
    accounts.append({
        "email": email,
        "password_enc": _encode(password),
        "imap_host": imap_host,
        "imap_port": imap_port,
        "label": label or email,
    })
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    return True


def remove_account(email: str) -> bool:
    """Elimina una cuenta. Devuelve False si no existe."""
    accounts = load_accounts_full()
    new_accounts = [a for a in accounts if a["email"] != email]
    if len(new_accounts) == len(accounts):
        return False
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(new_accounts, f, indent=2, ensure_ascii=False)
    return True


def test_account(email: str, password: str,
                 imap_host: str = "imap.gmail.com",
                 imap_port: int = 993) -> tuple:
    """Prueba conexión IMAP. Devuelve (success, message)."""
    import imaplib
    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        mail.login(email, password)
        mail.logout()
        return True, "Conexión OK"
    except imaplib.IMAP4.error as e:
        return False, f"Error IMAP: {e}"
    except Exception as e:
        return False, f"Error: {e}"