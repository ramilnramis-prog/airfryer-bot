"""B2B Seller Product Traffic Factory -- client -> product -> campaign data
layer. Plain JSON-file storage under content/b2b/ (same convention already
used by content/autopilot/<campaign>/*.json throughout this project), NOT a
database table. No network calls anywhere in this module.

Storage layout:
    content/b2b/clients/<client_id>/client.json
    content/b2b/clients/<client_id>/products/<product_id>/product.json
    content/b2b/clients/<client_id>/products/<product_id>/references/
        references-index.json
        <uploaded files>
    content/b2b/clients/<client_id>/products/<product_id>/campaigns/<campaign_id>/campaign.json
    content/b2b/clients/<client_id>/products/<product_id>/campaigns/<campaign_id>/generated/
        scenes/ videos/ dzen/ publishing/ performance/ delivery/
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

B2B_ROOT_REL = "content/b2b"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- entities ----------------------------------------------------------------

@dataclass
class Client:
    client_id: str
    name: str
    contact: str = ""
    created_at: str = field(default_factory=utcnow_iso)


PRODUCT_MARKETPLACES = ("ozon", "wildberries", "yandex_market", "other")


@dataclass
class Product:
    product_id: str
    client_id: str
    product_name: str
    marketplace: str = "ozon"
    marketplace_url: str = ""
    marketplace_article: str = ""
    category: str = ""
    target_audience: str = ""
    main_pain: str = ""
    product_description: str = ""
    created_at: str = field(default_factory=utcnow_iso)


PRODUCT_REFERENCE_ROLES = ("front", "top", "side", "detail", "packaging", "other")


@dataclass
class ProductReference:
    product_id: str
    file_path: str
    role: str = "other"
    approved: bool = False
    notes: str = ""


CAMPAIGN_GOALS = ("external_traffic", "marketplace_sales", "awareness", "content_testing")
CAMPAIGN_PLATFORMS = ("youtube_shorts", "instagram_reels", "tiktok", "vk_clips", "dzen")
CAMPAIGN_STATUSES = ("draft", "ready_for_generation", "generating",
                    "ready_for_owner_review", "delivered")


@dataclass
class Campaign:
    campaign_id: str
    client_id: str
    product_id: str
    campaign_goal: str = "external_traffic"
    platforms: list = field(default_factory=lambda: list(CAMPAIGN_PLATFORMS))
    status: str = "draft"
    created_at: str = field(default_factory=utcnow_iso)


# -- path helpers --------------------------------------------------------------

def b2b_root(repo_root: str = ".") -> Path:
    return Path(repo_root) / B2B_ROOT_REL


def client_dir(client_id: str, repo_root: str = ".") -> Path:
    return b2b_root(repo_root) / "clients" / client_id


def product_dir(client_id: str, product_id: str, repo_root: str = ".") -> Path:
    return client_dir(client_id, repo_root) / "products" / product_id


def references_dir(client_id: str, product_id: str, repo_root: str = ".") -> Path:
    return product_dir(client_id, product_id, repo_root) / "references"


def campaign_dir(client_id: str, product_id: str, campaign_id: str, repo_root: str = ".") -> Path:
    return product_dir(client_id, product_id, repo_root) / "campaigns" / campaign_id


def campaign_generated_dir(client_id: str, product_id: str, campaign_id: str, repo_root: str = ".") -> Path:
    return campaign_dir(client_id, product_id, campaign_id, repo_root) / "generated"


GENERATED_SUBDIRS = ("scenes", "videos", "dzen", "publishing", "performance", "delivery")


# -- client CRUD --------------------------------------------------------------

def save_client(client: Client, repo_root: str = ".") -> Path:
    d = client_dir(client.client_id, repo_root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "client.json"
    path.write_text(json.dumps(asdict(client), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_client(client_id: str, repo_root: str = ".") -> Client:
    path = client_dir(client_id, repo_root) / "client.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Client(**data)


def list_clients(repo_root: str = ".") -> list:
    root = b2b_root(repo_root) / "clients"
    if not root.is_dir():
        return []
    clients = []
    for d in sorted(root.iterdir()):
        if (d / "client.json").is_file():
            clients.append(load_client(d.name, repo_root))
    return clients


# -- product CRUD --------------------------------------------------------------

def save_product(product: Product, repo_root: str = ".") -> Path:
    d = product_dir(product.client_id, product.product_id, repo_root)
    d.mkdir(parents=True, exist_ok=True)
    (d / "references").mkdir(parents=True, exist_ok=True)
    (d / "campaigns").mkdir(parents=True, exist_ok=True)
    path = d / "product.json"
    path.write_text(json.dumps(asdict(product), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_product(client_id: str, product_id: str, repo_root: str = ".") -> Product:
    path = product_dir(client_id, product_id, repo_root) / "product.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Product(**data)


def list_products(client_id: str, repo_root: str = ".") -> list:
    root = client_dir(client_id, repo_root) / "products"
    if not root.is_dir():
        return []
    products = []
    for d in sorted(root.iterdir()):
        if (d / "product.json").is_file():
            products.append(load_product(client_id, d.name, repo_root))
    return products


def list_all_products(repo_root: str = ".") -> list:
    products = []
    for client in list_clients(repo_root):
        products.extend(list_products(client.client_id, repo_root))
    return products


# -- product reference CRUD -----------------------------------------------------

def _references_index_path(client_id: str, product_id: str, repo_root: str = ".") -> Path:
    return references_dir(client_id, product_id, repo_root) / "references-index.json"


def save_references(client_id: str, product_id: str, refs: list, repo_root: str = ".") -> Path:
    d = references_dir(client_id, product_id, repo_root)
    d.mkdir(parents=True, exist_ok=True)
    path = _references_index_path(client_id, product_id, repo_root)
    path.write_text(json.dumps([asdict(r) for r in refs], ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_references(client_id: str, product_id: str, repo_root: str = ".") -> list:
    path = _references_index_path(client_id, product_id, repo_root)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ProductReference(**r) for r in data]


def add_reference(client_id: str, product_id: str, file_path: str, role: str = "other",
                  approved: bool = False, notes: str = "", repo_root: str = ".") -> list:
    refs = load_references(client_id, product_id, repo_root)
    refs.append(ProductReference(product_id=product_id, file_path=file_path,
                                 role=role, approved=approved, notes=notes))
    save_references(client_id, product_id, refs, repo_root)
    return refs


# -- campaign CRUD --------------------------------------------------------------

def save_campaign(campaign: Campaign, repo_root: str = ".") -> Path:
    d = campaign_dir(campaign.client_id, campaign.product_id, campaign.campaign_id, repo_root)
    d.mkdir(parents=True, exist_ok=True)
    gen = d / "generated"
    for sub in GENERATED_SUBDIRS:
        (gen / sub).mkdir(parents=True, exist_ok=True)
    path = d / "campaign.json"
    path.write_text(json.dumps(asdict(campaign), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_campaign(client_id: str, product_id: str, campaign_id: str, repo_root: str = ".") -> Campaign:
    path = campaign_dir(client_id, product_id, campaign_id, repo_root) / "campaign.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Campaign(**data)


def list_campaigns(client_id: str, product_id: str, repo_root: str = ".") -> list:
    root = product_dir(client_id, product_id, repo_root) / "campaigns"
    if not root.is_dir():
        return []
    campaigns = []
    for d in sorted(root.iterdir()):
        if (d / "campaign.json").is_file():
            campaigns.append(load_campaign(client_id, product_id, d.name, repo_root))
    return campaigns


def list_all_campaigns(repo_root: str = ".") -> list:
    campaigns = []
    for product in list_all_products(repo_root):
        campaigns.extend(list_campaigns(product.client_id, product.product_id, repo_root))
    return campaigns
