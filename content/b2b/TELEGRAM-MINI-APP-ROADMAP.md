# Telegram Mini App Roadmap -- B2B Seller Traffic Factory

Design doc only. **No Telegram bot or Mini App is implemented at this step.**
This describes the intended path from the current web-only `/traffic-factory`
entry to a Telegram-native experience, and what NOT to build in the first
version.

---

## Phase 1 -- Web app only (current state)

The public entry point is a plain web page: `/traffic-factory` (landing),
`/traffic-factory/start` (beta-gated wizard entry, wraps `/b2b/seller/*`),
`/traffic-factory/demo`, `/traffic-factory/status/{request_id}`. No Telegram
integration exists yet. This is where the product is today.

## Phase 2 -- Telegram bot with a button

A minimal Telegram bot (separate from any autoposting bot work) that:

- Replies to `/start` with a short pitch (reuse copy from
  `content/b2b/PUBLIC-ENTRY-COPY.md`) and one inline button: "Создать
  контент-пакет".
- The button opens `/traffic-factory/start` as a normal external link
  (`url` button, not `web_app` yet) -- the seller leaves Telegram and
  fills the wizard in their regular browser exactly as today.
- No file uploads happen inside Telegram at this phase; the bot is purely
  a discovery/entry-point channel (e.g. for sellers who found the offer
  through a Telegram channel/ad).

## Phase 3 -- Telegram Mini App opens the same wizard

Once Phase 2 is validated:

- Register a Telegram Mini App (`web_app` button / menu button) that opens
  `/traffic-factory/start` inside Telegram's in-app browser instead of an
  external link -- same routes, same backend, same wizard steps 1-6. No
  separate Mini-App-only backend is built; the Mini App is a thin wrapper
  around the existing web flow.
- Add Telegram WebApp JS SDK initialization (`Telegram.WebApp.ready()`,
  theme params for dark/light matching Telegram's theme) purely as a
  presentation-layer adjustment to the existing Jinja2 templates -- no
  change to route logic or storage.
- Use `Telegram.WebApp.initData` to identify the seller (their Telegram
  user id) and prefill `client_name`/`contact` on Step 1 if already known
  from a prior session -- convenience only, not authentication (the beta
  access code gate stays as the actual gate).

### Screens needed inside Telegram

Same six wizard steps as the web wizard (`/b2b/seller/start` through
`step6`), rendered in Telegram's in-app browser:

1. Товар (product basics)
2. Фото товара (reference photos)
3. Покупатель и позиционирование
4. Что AI понял про товар (review/approve)
5. Настройки контент-пакета
6. Чеклист готовности + "Проверить будущий контент-пакет" / "Собрать
   готовый ZIP с материалами"

No new screens are needed -- the Mini App reuses the same templates.

### File uploads inside Telegram

Telegram Mini Apps run inside a WebView with normal HTML file input support
in recent Telegram client versions, so the existing
`<input type="file" multiple>` upload flow (Step 2) should work unmodified
in most cases. As a fallback for older Telegram clients or platforms where
in-app file pickers are unreliable, Phase 3 should also support: the seller
sending product photos directly to the bot as Telegram messages (bot
receives `photo`/`document` updates, downloads via Bot API `getFile`, saves
them into the same `references/uploaded/` folder tied to their session).
This fallback is optional and only built if in-Mini-App upload proves
unreliable in testing -- not built by default.

### Delivering the ZIP / result link back to the seller

Once a delivery kit is built (via the existing
`api.media_pipeline.b2b_delivery_kit.build_delivery_kit_zip`), the bot sends
the seller a message with:

- a direct download link to `/b2b/campaigns/{campaign_id}/delivery-kit.zip`
  (already an existing route), or
- the Bot API's `sendDocument` if the file should be delivered as a native
  Telegram file attachment instead of a link (nice-to-have, not required
  for MVP -- a link is sufficient).

The `/traffic-factory/status/{request_id}` page (already built) can be
linked from the bot as "Проверить статус" so the seller can check progress
without re-entering the Mini App.

## Phase 4 -- Notifications

Once a campaign's content package is ready for review, the bot proactively
messages the seller (`sendMessage`) with a link to
`/traffic-factory/status/{request_id}` or the campaign page. Requires the
seller to have started a conversation with the bot first (Telegram API
constraint) -- captured as part of Phase 2's `/start` flow.

---

## What NOT to do in the first version

- Do NOT build a separate Mini-App-specific backend or duplicate the wizard
  logic -- always reuse `/b2b/seller/*` and `/traffic-factory/*` routes.
- Do NOT implement real authentication via Telegram Login Widget /
  `initData` signature verification in Phase 3 -- `initData` is used only
  for convenience prefill, the beta access code remains the actual gate
  until real auth is explicitly requested.
- Do NOT auto-post to YouTube/Instagram/TikTok/VK/Dzen from the bot -- see
  `content/b2b/AUTOPOSTING-ROADMAP.md`, which is a separate, later track.
- Do NOT call OpenAI/Higgsfield from the bot directly -- content generation
  stays server-side, triggered manually the same way it is today.
- Do NOT store Telegram bot tokens or any secrets in this repository; they
  belong in environment variables / secret managers, never committed.
