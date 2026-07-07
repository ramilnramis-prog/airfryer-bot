# Autoposting Roadmap -- B2B Seller Product Traffic Factory

Design doc only. **No real autoposting is implemented at this step.** Every
phase below except Phase 1 requires explicit, separate future work and
explicit owner sign-off before any code that posts on a client's behalf is
written or run.

---

## Phase 1 -- Manual upload-ready kit (current state)

The system produces a **delivery kit** (`DELIVERY-KIT.zip`): ready-to-upload
MP4s sorted by publishing day, Dzen articles with images/tags/pinned
comments, platform-specific metadata (titles/captions/hashtags/CTA), a
publishing plan (day/time/platform), and a performance tracker the seller
fills in by hand after publishing.

The seller (or their social media manager) uploads everything themselves
through each platform's normal app/website. Nothing in this system ever
calls a social platform's API. This is where the product is today.

## Phase 2 -- OAuth connections

Before any post can be scheduled or sent automatically, the seller must
explicitly connect their own accounts via OAuth on each platform:

- **YouTube** -- Google OAuth 2.0, scope `https://www.googleapis.com/auth/youtube.upload`
  (and `youtube` for read access to channel/video status).
- **Instagram** -- Meta OAuth via a connected Facebook Page + Instagram
  Business/Creator account (Instagram login alone is not sufficient for
  publishing APIs).
- **TikTok** -- TikTok for Developers OAuth 2.0, `video.publish` /
  `video.upload` scopes under the Content Posting API.
- **VK** -- VK OAuth (VK ID / VK API), scope covering video/clips upload for
  the relevant community/account.

Each platform requires:
- registering an app with that platform and going through their **app
  review** process before scopes needed for posting are granted for
  real (non-test) accounts;
- storing refresh tokens securely, per-client, with a way for the seller to
  revoke access at any time;
- respecting each platform's **rate limits** and **content policies**
  (e.g. YouTube daily upload quota, TikTok content review delays, Meta's
  publishing rate limits per app/user).

No token storage or OAuth flow exists in this codebase yet -- this phase
is unimplemented.

## Phase 3 -- Scheduled posting

Once OAuth is connected for a given platform:

1. The seller reviews the generated publishing queue in the web UI and
   explicitly **approves** it (or edits/removes individual items first --
   nothing posts by default just because it was generated).
2. The system posts through each platform's **official API only**, at the
   approved times, one call per scheduled item, no silent retries on
   failure (matches this project's existing "retries=0, fail closed"
   convention used throughout the local content factory).
3. Every post attempt is **logged**: request payload (no secrets), response,
   resulting post ID/URL, timestamp, success/failure.
4. **Failed posts** are surfaced to the seller (and us) explicitly --
   never silently dropped, never auto-retried without a human decision.
   A failed post keeps its scheduled slot marked `failed`, not
   `published`, until manually resolved.

Known official upload/publish surfaces (subject to that platform's current
terms, scopes, and review requirements at implementation time):

- **YouTube**: YouTube Data API v3, `videos.insert` (resumable upload),
  plus `videos.update` for metadata. Subject to daily quota units and
  channel verification requirements for public uploads.
- **Instagram**: Meta's **Content Publishing API** (part of the Instagram
  Graph API), for supported account types (Business/Creator) and supported
  content types (Reels, feed video, etc.) -- coverage and eligibility
  should be re-verified against Meta's current docs at implementation
  time, since supported media types and account requirements change.
- **TikTok**: **TikTok Content Posting API**, direct-post endpoints, gated
  by app review and the creator's TikTok account permissions.
- **VK**: VK API video/clips upload methods, gated by the connected
  community/account's own permissions.
- **Dzen**: Yandex Dzen currently has **no confirmed stable public
  posting API** for this use case. Support here must be verified
  separately before Phase 3 work starts -- until an official integration
  is confirmed and tested, Dzen publishing stays **manual, or at most
  RSS-based** (Dzen supports importing posts via RSS feed for some account
  types) rather than a direct authenticated API call. Do not assume API
  parity with the video platforms above.

## Phase 4 -- Performance loop

Once posts are live and logged:

1. **Collect metrics** on a schedule (e.g. daily) via each platform's
   read/analytics API (where available) instead of manual CSV entry --
   reusing the same metric shape already defined in the local
   `performance-tracking/master-performance-tracker.csv` (views, likes,
   comments, shares, saves, clicks).
2. Run the same analysis already built for the single-campaign pipeline
   (`content_factory_performance.analyze_performance`): best videos/hooks/
   angles/styles/platforms by engagement rate, weak performers, repeated
   patterns.
3. **Recommend the next creative batch** automatically (angles to
   reinforce, hooks to repeat, what to avoid) -- surfaced to the seller for
   approval before any new generation run, never auto-triggering paid
   generation on its own.

---

## Cross-cutting requirements for Phases 2-4 (not yet built)

- Per-client OAuth token storage, encrypted at rest, with a visible
  "connected accounts" UI and a revoke button.
- An explicit **owner-approval gate** before ANY scheduled post fires --
  this system's own established pattern (`candidate_status` never
  auto-accepts; `publish_status` starts `not_published` and only a human
  action moves it forward) should be carried into the autoposting layer
  unchanged.
- Structured logs for every post attempt (success and failure), retained
  long enough to audit/debug.
- Per-platform rate-limit awareness baked into the scheduler, not just
  hoped to work.
- A kill switch: ability to pause all scheduled posting for a client or
  platform instantly.

**None of the above exists in code today.** This document exists to make
the shape of that future work explicit, not to promise a delivery date.
