import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ZohoClient:
    """A client for interacting with the Zoho Books API."""

    BASE_URL = "https://www.zohoapis.com/books/v3"
    TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, organization_id: str) -> None:
        """
        Initialize the ZohoClient.

        :param client_id: Zoho client ID
        :param client_secret: Zoho client secret
        :param redirect_uri: Redirect URI for OAuth
        :param organization_id: Zoho organization ID
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.organization_id = organization_id
        self.temp_file = "zoho_refresh_token.json"
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.logger = logging.getLogger(__name__)
        self._load_refresh_token()
        self._ensure_auth()

    def get_grant_token(self, code: str) -> bool:
        """
        Get a grant token using the provided authorization code.

        :param code: Authorization code
        :return: True if successful, False otherwise
        """
        params = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }

        response = requests.post(self.TOKEN_URL, params=params)

        if response.status_code == 200:
            data = response.json()
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            self.token_expiry = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))
            self._store_refresh_token()
            self.logger.info("Successfully obtained grant token and refresh token.")
            return True
        else:
            self.logger.error(f"Grant token request failed with status code: {response.status_code}")
            self.logger.error(f"Response: {response.text}")
            return False

    def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the stored refresh token.

        :return: True if successful, False otherwise
        """
        if not self.refresh_token:
            self._load_refresh_token()

        if not self.refresh_token:
            self.logger.error("No refresh token available.")
            return False

        params = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "refresh_token",
        }

        response = requests.post(self.TOKEN_URL, params=params)

        if response.status_code == 200:
            data = response.json()
            self.access_token = data.get("access_token")
            self.token_expiry = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))
            self.logger.info("Successfully refreshed access token.")
            return True
        else:
            self.logger.error(f"Failed to refresh access token. Status code: {response.status_code}")
            self.logger.error(f"Response: {response.text}")
            return False

    def _store_refresh_token(self) -> None:
        """Store the refresh token in a local file."""
        with open(self.temp_file, "w") as f:
            json.dump({"refresh_token": self.refresh_token}, f)

    def _load_refresh_token(self) -> None:
        """Load the refresh token from a local file."""
        if os.path.exists(self.temp_file):
            with open(self.temp_file) as f:
                data = json.load(f)
                self.refresh_token = data.get("refresh_token")

    def _ensure_auth(self) -> None:
        """
        Ensure that we have a valid refresh token and access token.
        """
        if not self.refresh_token:
            self.logger.info("No refresh token found. Please authorize the application.")
            code = input("Enter the authorization code: ")
            if not self.get_grant_token(code):
                raise ValueError("Failed to obtain grant token.")
        self._ensure_valid_token()

    def _ensure_valid_token(self) -> bool:
        """
        Ensure that we have a valid access token, refreshing if necessary.

        :return: True if a valid token is available, False otherwise
        """
        if not self.access_token or (self.token_expiry and datetime.now() >= self.token_expiry):
            return self.refresh_access_token()
        return True

    def get_access_token(self) -> str | None:
        """
        Get a valid access token, refreshing if necessary.

        :return: Access token if available, None otherwise
        """
        if self._ensure_valid_token():
            return self.access_token
        return None

    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Make an authenticated request to the Zoho Books API.

        :param method: HTTP method (GET, POST, etc.)
        :param endpoint: API endpoint
        :param kwargs: Additional arguments for the request
        :return: Response object
        """
        access_token = self.get_access_token()
        if not access_token:
            self.logger.error("Failed to obtain a valid access token.")
            raise ValueError("Failed to obtain a valid access token.")

        url = f"{self.BASE_URL}/{endpoint}"
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        params = kwargs.pop("params", {})
        params["organization_id"] = self.organization_id

        self.logger.info(f"Making {method} request to {url}")
        response = requests.request(method, url, headers=headers, params=params, **kwargs)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error occurred: {e}")
            self.logger.error(f"Response content: {response.text}")
            raise

        self.logger.info(f"Request to {url} successful")
        return response

    def list_invoices(self) -> list[dict[str, Any]]:
        """
        List all invoices.

        :return: List of invoice dictionaries
        """
        response = self._make_request("GET", "invoices")
        return response.json().get("invoices", [])

    def download_invoice(self, invoice_id: str) -> None:
        """
        Download an invoice as a PDF.

        :param invoice_id: ID of the invoice to download
        """
        response = self._make_request("GET", f"invoices/{invoice_id}", params={"accept": "pdf"})
        with open(f"{invoice_id}.pdf", "wb") as f:
            f.write(response.content)
        self.logger.info(f"Invoice PDF downloaded successfully as {invoice_id}.pdf")

    def create_item(self, name: str, rate: float, description: str = "") -> str | None:
        """
        Create a new item.

        :param name: Name of the item
        :param rate: Rate of the item
        :param description: Description of the item
        :return: Item ID if created successfully, None otherwise
        """
        data = {
            "name": name,
            "rate": rate,
            "description": description,
        }
        response = self._make_request("POST", "items", json=data)
        return response.json().get("item", {}).get("item_id")

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        """
        Get details of a specific item.

        :param item_id: ID of the item to retrieve
        :return: Item details dictionary if found, None otherwise
        """
        response = self._make_request("GET", f"items/{item_id}")
        return response.json().get("item", {})

    def list_items(self) -> list[dict[str, Any]]:
        """
        List all items.

        :return: List of item dictionaries
        """
        response = self._make_request("GET", "items")
        return response.json().get("items", [])

    def create_invoice(self, customer_id: str, items: list[str], quantities: list[int]) -> str | None:
        """
        Create a new invoice.

        :param customer_id: ID of the customer
        :param items: List of item IDs
        :param quantities: List of quantities corresponding to the items
        :return: Invoice ID if created successfully, None otherwise
        """
        line_items = []
        for item_id, quantity in zip(items, quantities, strict=False):
            item = self.get_item(item_id)
            if item:
                line_items.append({
                    "item_id": item_id,
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "rate": item.get("rate"),
                    "quantity": quantity
                })

        data = {
            "customer_id": customer_id,
            "line_items": line_items
        }
        response = self._make_request("POST", "invoices", json=data)
        return response.json().get("invoice", {}).get("invoice_id")

    def create_contact(self, contact_data: dict[str, Any]) -> str | None:
        """
        Create a new contact.

        :param contact_data: Dictionary containing contact information
        :return: Contact ID if created successfully, None otherwise
        """
        response = self._make_request("POST", "contacts", json=contact_data)
        return response.json().get("contact", {}).get("contact_id")

    def list_contacts(self) -> list[dict[str, Any]]:
        """
        List all contacts.

        :return: List of contact dictionaries
        """
        response = self._make_request("GET", "contacts")
        return response.json().get("contacts", [])

    def get_contact(self, contact_id: str) -> dict[str, Any] | None:
        """
        Get details of a specific contact.

        :param contact_id: ID of the contact to retrieve
        :return: Contact details dictionary if found, None otherwise
        """
        response = self._make_request("GET", f"contacts/{contact_id}")
        return response.json().get("contact", {})

    def mark_contact_active(self, contact_id: str) -> bool:
        """
        Mark a contact as active.

        :param contact_id: ID of the contact to mark as active
        :return: True if successful, False otherwise
        """
        response = self._make_request("POST", f"contacts/{contact_id}/active")
        return response.status_code == 200

    def mark_contact_inactive(self, contact_id: str) -> bool:
        """
        Mark a contact as inactive.

        :param contact_id: ID of the contact to mark as inactive
        :return: True if successful, False otherwise
        """
        response = self._make_request("POST", f"contacts/{contact_id}/inactive")
        return response.status_code == 200



if __name__ == "__main__":
    # zoho_client = ZohoClient(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, ORGANIZATION_ID)
