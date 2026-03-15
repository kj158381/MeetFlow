"""
services/contacts_service.py
Google People API — sync contacts from Google account.
"""
import logging, requests
logger = logging.getLogger(__name__)

PEOPLE_BASE = "https://people.googleapis.com/v1"

def fetch_google_contacts(access_token: str, page_size: int = 200) -> tuple[int, list]:
    """
    Returns (http_status_code, list_of_contact_dicts).
    Each dict: {name, email, phone, company, photo}
    """
    resp = requests.get(
        f"{PEOPLE_BASE}/people/me/connections",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "personFields": "names,emailAddresses,phoneNumbers,organizations,photos",
            "pageSize": page_size
        },
        timeout=10
    )
    if resp.status_code != 200:
        return resp.status_code, []

    data     = resp.json()
    contacts = []
    for person in data.get("connections", []):
        names   = person.get("names", [])
        emails  = person.get("emailAddresses", [])
        phones  = person.get("phoneNumbers", [])
        orgs    = person.get("organizations", [])
        name    = names[0].get("displayName", "")  if names  else ""
        email   = emails[0].get("value", "")       if emails else ""
        phone   = phones[0].get("value", "")       if phones else ""
        company = orgs[0].get("name", "")          if orgs   else ""
        if not name and not email:
            continue
        contacts.append({
            "name":    name or "(No name)",
            "email":   email,
            "phone":   phone,
            "company": company,
        })
    return 200, contacts
