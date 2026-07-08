# B2B Seller Traffic Factory -- MVP README

Admin-first MVP for running the B2B seller product traffic factory. We (the
agency) create clients/products/campaigns manually on behalf of a seller and
hand them a delivery kit -- there is no seller self-service signup yet.

## What this MVP is

A server-rendered admin flow (`/b2b/*`, FastAPI + Jinja2) plus a matching set
of CLI commands (`python -m api.media_pipeline.cli b2b-*`) that together take
an admin through:

1. create a client
2. create a product for that client (marketplace listing details + uploaded
   product reference photos)
3. approve at least 3 of the uploaded product reference photos
4. create a campaign for the product
5. run a dry-run (a plan, zero paid/API calls) to see the planned content
   package and cost estimate
6. build a delivery kit (explanatory docs + folder shape the seller receives)
7. download the delivery kit as a ZIP

Nothing beyond step 7 exists yet -- see "What is NOT yet implemented" below.

## How to create the demo

```
python -m api.media_pipeline.cli b2b-seed-demo
```

Idempotent -- safe to run more than once. Creates `demo-ozon-airfryer` /
`airfryer-silicone-form` / `coating-protect-2026-07` with 4 pre-approved
product references (reused read-only from the existing product-lock asset
set) and a legacy adapter manifest pointing at the already-generated
`content/autopilot/coating-protect-2026-07` output tree (not copied).

## How to open /b2b

Start the API (`uvicorn api.main:app --reload` or however this project's
FastAPI app is normally run) and open `/b2b` in a browser. The dashboard
shows client/product/campaign counts and a link to the demo campaign once
seeded.

**Do not open files under `api/templates/` directly in a file explorer or
text editor and expect them to look like a web page.** They are Jinja2
templates -- raw `{% ... %}` / `{{ ... }}` markers are only resolved when
FastAPI renders them through a route. Always start the app and open the
actual URL (`/traffic-factory`, `/b2b`, etc.) in a browser.

## How to upload a product

From the dashboard, click **+ Create new product** (`/b2b/products/new`).
Fill in client name/contact, product name, marketplace, article, URL,
category, target audience, main pain, description, and attach one or more
product reference photos (front/top/side/detail/packaging). Submitting
creates the client (if new), the product, and saves the uploaded images
under `content/b2b/clients/<client_id>/products/<product_id>/references/uploaded/`
with `approved=false` by default -- nothing is auto-approved.

## How to approve references

On the product detail page (`/b2b/products/{product_id}`), each uploaded
reference has an `approve`/`unapprove` button and a `role` dropdown
(front/top/side/detail/packaging/other). A campaign cannot be created until
at least 3 references are approved -- this is enforced both in the UI (the
"Create campaign" button/form is hidden below the threshold) and in the
underlying policy gate (`B2BReferencePolicyError`, fails closed).

## How to run a dry-run

On the campaign detail page (`/b2b/campaigns/{campaign_id}`), click
**Run dry-run**, or via CLI:

```
python -m api.media_pipeline.cli b2b-campaign-dry-run \
  --client <client_id> --product <product_id> --campaign <campaign_id>
```

Writes `campaign-dry-run.json` and a human-readable `campaign-dry-run.md`
under `.../campaigns/<campaign_id>/generated/`: client/product summary,
approved and rejected references, planned scenes/videos/Dzen articles/
publishing queue, estimated OpenAI image calls, estimated local MP4
renders, estimated cost, and a safety policy summary. **Zero OpenAI/
Higgsfield calls** -- this is a plan, not a generation run.

## How to build a delivery kit

On the campaign detail page, click **Build delivery kit**, or via CLI:

```
python -m api.media_pipeline.cli b2b-build-delivery-kit \
  --client <client_id> --product <product_id> --campaign <campaign_id>
```

Writes `OWNER-README.md`, `PRODUCT-SUMMARY.md`, `CAMPAIGN-PLAN.md`,
`REFERENCE-POLICY.md`, `NEXT-STEPS.md`, and the `upload-ready/`,
`publishing-plan/`, `performance-tracking/` folders under
`.../campaigns/<campaign_id>/generated/delivery/`, then zips it all into
`DELIVERY-KIT.zip`. Same fail-closed reference policy gate as the dry-run.
Downloadable from the campaign page once built.

## What is NOT yet implemented

- **Real content generation for arbitrary seller products.** The dry-run and
  delivery kit describe a plan; they do not call OpenAI Images, run the
  local video renderer, or write real scenes/videos/Dzen articles for a
  newly onboarded product. That wiring exists today only for the original
  single-campaign pipeline (`content/autopilot/coating-protect-2026-07`),
  referenced by the demo campaign's legacy adapter manifest.
- **Payments.** No billing, invoicing, or subscription logic.
- **Login / seller self-service.** No auth, no seller accounts -- `/b2b/*`
  routes have no `X-API-Key` or session auth (documented gap in
  `api/b2b.py`'s module docstring); admin-only, trusted-network use for now.
- **Auto-posting.** Nothing in this system ever calls a social platform's
  API. See `content/b2b/AUTOPOSTING-ROADMAP.md` for the phased plan and
  OAuth requirements per platform (YouTube, Instagram, TikTok, VK, Dzen).
- **OAuth integrations.** No platform account connections of any kind exist
  yet -- a prerequisite for any future auto-posting phase.
