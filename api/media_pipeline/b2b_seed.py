"""Demo seed: migrates the EXISTING coating-protect-2026-07 campaign into the
new B2B client -> product -> campaign shape, without physically copying any
of the old generated files (too risky/heavy) -- instead writes a legacy
adapter manifest that points at the existing content/autopilot/... paths.
No network calls."""
from __future__ import annotations

import json
from pathlib import Path

from . import b2b_storage as st

DEMO_CLIENT_ID = "demo-ozon-airfryer"
DEMO_PRODUCT_ID = "airfryer-silicone-form"
DEMO_CAMPAIGN_ID = "coating-protect-2026-07"

# Only the already-reviewed, approved product-only references (real-v1) --
# never any generated/kitchen/food/hands image. Reused read-only, not copied.
DEMO_REFERENCES = (
    ("assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_45deg_master.png",
     "front", "45-degree hero angle, approved product-lock master"),
    ("assets/product-lock/airfryer-silicone-form/references/real-v1/product/product_top_master.png",
     "top", "top-down view, approved product-lock master"),
    ("assets/product-lock/airfryer-silicone-form/references/real-v1/handles/both_handles_master.png",
     "detail", "both corner handle tabs, approved product-lock master"),
    ("assets/product-lock/airfryer-silicone-form/references/real-v1/bottom/bottom_loop_master.png",
     "detail", "ribbed bottom, approved product-lock master"),
)

# Points at the EXISTING legacy campaign output tree (content/autopilot/
# coating-protect-2026-07/generated/...) instead of duplicating it under
# content/b2b/. Purely descriptive/read-only -- the b2b layer never writes
# into these paths.
LEGACY_CAMPAIGN_ROOT = "content/autopilot/coating-protect-2026-07"
LEGACY_ADAPTER_POINTERS = {
    "scenes": f"{LEGACY_CAMPAIGN_ROOT}/generated/product-reference-only-scene-v2",
    "videos": f"{LEGACY_CAMPAIGN_ROOT}/generated/content-factory/video-renders",
    "dzen": f"{LEGACY_CAMPAIGN_ROOT}/generated/content-factory/dzen-posts",
    "dzen_publishing_kits": f"{LEGACY_CAMPAIGN_ROOT}/generated/content-factory/dzen-publishing",
    "publishing": f"{LEGACY_CAMPAIGN_ROOT}/generated/content-factory/publishing",
    "performance": f"{LEGACY_CAMPAIGN_ROOT}/generated/content-factory/performance-tracking",
    "review_dashboard": f"{LEGACY_CAMPAIGN_ROOT}/generated/content-factory/review/index.html",
}


def write_legacy_adapter_manifest(repo_root: str = ".") -> dict:
    manifest = {
        "note": ("Adapter manifest -- points at the EXISTING legacy campaign output "
                "under content/autopilot/coating-protect-2026-07/generated/ instead of "
                "physically copying it into the new content/b2b/ layout. Nothing under "
                "these pointer paths is owned or modified by the b2b layer."),
        "legacy_campaign_root": LEGACY_CAMPAIGN_ROOT,
        "pointers": LEGACY_ADAPTER_POINTERS,
    }
    gen_dir = st.campaign_generated_dir(DEMO_CLIENT_ID, DEMO_PRODUCT_ID, DEMO_CAMPAIGN_ID, repo_root)
    gen_dir.mkdir(parents=True, exist_ok=True)
    path = gen_dir / "legacy-campaign-adapter.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"manifest_path": str(path), "manifest": manifest}


def seed_demo(repo_root: str = ".") -> dict:
    """Creates (idempotently -- safe to call more than once) the demo
    client/product/references/campaign + legacy adapter manifest. Never
    touches OpenAI/Higgsfield, never copies old generated files."""
    client = st.Client(client_id=DEMO_CLIENT_ID, name="Demo Ozon Seller (Airfryer)",
                       contact="ramilnramis@gmail.com")
    st.save_client(client, repo_root)

    product = st.Product(
        product_id=DEMO_PRODUCT_ID, client_id=DEMO_CLIENT_ID,
        product_name="Силиконовая форма для аэрогриля",
        marketplace="ozon",
        marketplace_url=("https://ozon.ru/product/forma-dlya-aerogrilya-silikonovaya-"
                         "antiprigarnaya-aksessuar-dlya-aerogrilya-forma-dlya-vypechki-"
                         "1931921872/?hs=1&utm_campaign=vendor_org_1751712_airfryer"
                         "&utm_medium=social&utm_source=youtube"),
        marketplace_article="1931921872",
        category="Кухонные принадлежности",
        target_audience="Владельцы аэрогрилей, которым надоело отмывать жирную корзину",
        main_pain="Чаша/корзина аэрогриля пачкается жиром и трудно отмывается, "
                 "антипригарное покрытие царапается и стирается",
        product_description=("Квадратная силиконовая форма-вкладыш для аэрогриля: "
                            "тёмно-серый матовый силикон, плоские ручки по углам с "
                            "прорезями, рифлёное дно. Ставится внутрь корзины аэрогриля "
                            "перед готовкой -- жир и соус остаются в форме, а не на "
                            "решётке, мыть нужно только форму."),
    )
    st.save_product(product, repo_root)

    refs = [
        st.ProductReference(product_id=DEMO_PRODUCT_ID, file_path=path, role=role,
                            approved=True, notes=notes)
        for path, role, notes in DEMO_REFERENCES
    ]
    st.save_references(DEMO_CLIENT_ID, DEMO_PRODUCT_ID, refs, repo_root)

    campaign = st.Campaign(
        campaign_id=DEMO_CAMPAIGN_ID, client_id=DEMO_CLIENT_ID, product_id=DEMO_PRODUCT_ID,
        campaign_goal="external_traffic",
        platforms=list(st.CAMPAIGN_PLATFORMS),
        status="ready_for_owner_review",  # legacy campaign already has real output
    )
    st.save_campaign(campaign, repo_root)

    adapter = write_legacy_adapter_manifest(repo_root)

    return {
        "client_id": DEMO_CLIENT_ID, "product_id": DEMO_PRODUCT_ID,
        "campaign_id": DEMO_CAMPAIGN_ID, "references_count": len(refs),
        "legacy_adapter_manifest_path": adapter["manifest_path"],
    }
