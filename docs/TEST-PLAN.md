# LinkedIn MCP — Live Test Plan

Owner: Ram. Scope: the fork at `maree217/linkedin-mcp-server`. Every test here runs against live LinkedIn through the MCP, with `uv run` so the workspace code is what executes. Unit tests (`uv run pytest`) are the floor, not the plan.

Conventions
- **Target** is who the test runs against. Read tests use public profiles or Ram's own account. Write tests use a consenting or sacrificial account only, never a live prospect. ⚠ Ram to name the sacrificial targets in the table at the end.
- **Pass** is observable: a specific key in the returned JSON, a visible state change on LinkedIn, or a log line. "It returned something" is never a pass.
- **Interpretation** (satisfaction, ambition, trajectory) is labelled as interpretation and carries a confidence. The test checks the evidence was gathered and the label attached, not that the guess was right.
- Rate: LinkedIn is one browser session. Run tiers 1 to 3 on separate days from tier 4. Cap any single run at 15 profile reads (the outreach-sweep ceiling).

## Tier 0 — Plumbing (run first, every time)

| # | Test | Calls | Pass |
|---|---|---|---|
| 0.1 | Tool surface | `tools/list` over streamable-http | exactly 24 names incl. `get_captured_people`, `close_session` |
| 0.2 | Cold start | `get_my_profile` from a stopped server | profile sections returned; log shows `headless=True` and `Pruned ... caches at launch` |
| 0.3 | No window | same call, `osascript` list of foreground apps before/after | no new Chromium entry |
| 0.4 | Idle close | wait `LINKEDIN_BROWSER_IDLE_SECONDS`+15s | 0 processes matching `linkedin-mcp/profile`; profile dir < 100 MB |
| 0.5 | Cache cap | after 10 varied reads, `du -sh ~/.linkedin-mcp/profile/Default/Cache` | ≤ 60 MB |
| 0.6 | Warehouse soft-fail | `get_captured_company` with companion-api stopped | returns a `found: false`-style payload within 6s, no exception |
| 0.7 | Warehouse hit | companion-api running with a known capture; `get_person_profile(prefer_cache=True)` | `source: "warehouse"` in result, no browser launch logged |
| 0.8 | Session resilience | pull network for 10s mid-call | `NetworkError`, not re-login; next call succeeds without `--login` |
| 0.9 | Install drift | `cat ~/.local/share/uv/tools/mcp-server-linkedin/uv-receipt.toml` | `editable = ".../forks/linkedin-mcp-server"` |

## Tier 1 — The person

Given one profile URL, answer: who are they, what do they care about, how do they engage.

| # | Test | Calls | Pass |
|---|---|---|---|
| 1.1 | Identity | `get_person_profile(sections="main_profile,experience,education")` | name, headline, current role+company, ≥2 experience entries, no `section_errors` |
| 1.2 | Interests | `get_person_profile(sections="posts,interests")` (or `activity`) | ≥3 recent posts with dates; `references.posts` contains permalinks |
| 1.3 | Commenting approach | `get_person_profile(sections="comments")` | ≥5 comments, each with target post URL and the commenter's text; 0 mis-attributed @mentions (spot-check 3) |
| 1.4 | Who they talk to | `get_post_comments` on 2 of their posts | commenter list with profile URLs; author anchor is the header, not an @mention in the body (regression of fix 2661d3f) |
| 1.5 | Synthesis | Claude writes a 6-line brief from 1.1 to 1.4 | each claim cites the section it came from; interests and style labelled as interpretation |
| 1.6 | Creator-mode profile | repeat 1.1 to 1.3 on a profile whose primary button is Follow | same pass; `connection_state` populated |
| 1.7 | Sparse profile | a profile with <3 posts in 90 days | `posts` section returns cleanly with few entries; champion-scan would flag "low activity", not error |

## Tier 2 — The person in their organisation

Is this person settled, rising, restless, ambitious. This is interpretation built on evidence.

| # | Test | Calls | Pass |
|---|---|---|---|
| 2.1 | Tenure and trajectory | `experience` section: role changes inside the current employer | a timeline of titles with dates; promotion cadence computed |
| 2.2 | Voice vs employer | their last 10 posts vs `get_company_posts(company)` last 10 | overlap score (how many of their posts amplify the employer) plus a list of off-message topics |
| 2.3 | Engagement direction | `comments` section: who they comment on | share of comments on employer colleagues vs outsiders vs recruiters/vendors |
| 2.4 | Peer context | `get_company_employees(company, role filter)` for 5 peers at same level | peer tenure distribution, so the subject's tenure can be read relative to norm |
| 2.5 | Open-to signals | profile headline/about for "open to", hiring, job-seeking markers | flagged if present, with the quote |
| 2.6 | Judgement output | Claude's verdict: satisfaction / trajectory / ambition | each with a confidence (high/med/low) and the 1 to 2 evidence lines it rests on; a "cannot tell" is a valid answer |
| 2.7 | Absence handling | run 2.x on someone with no posts | output says "no signal", never infers unhappiness from silence |

## Tier 3 — The organisation (ties to frontier-deep people lens)

| # | Test | Calls | Pass |
|---|---|---|---|
| 3.1 | Company profile | `get_company_profile(slug)` | about, size, HQ, industry, specialities; `references` carries `company_urn` |
| 3.2 | Capability map | `get_company_employees(slug)` with 3 role queries (data/AI, architecture, delivery) | ≥10 people per query where the firm is >50 staff; dedup by profile URL |
| 3.3 | Hiring signal | `search_jobs(company)` + `get_job_details` on 3 | titles, locations, posted dates, required skills |
| 3.4 | Voice | `get_company_posts(slug)` last 10 | dates and text; themes extracted |
| 3.5 | frontier-deep contract | run frontier-deep's people lens on the same slug | consumes 3.1 to 3.4 output with no shape errors; its "known limit" (one rate-limited session) respected; run completes under 15 profile reads |
| 3.6 | Slug mismatch | `get_captured_company("Display Name With Spaces")` | either resolves or returns not-found; never a 500 (open question flagged in a104fad review) |
| 3.7 | Search | `search_people("Head of Data" + company)` and `search_companies("boutique advisory York")` | ≥5 results with URLs each |

## Tier 4 — Outreach writes (sacrificial targets only)

Each write tool must prove two things: it does the action when it should, and it does nothing when it can't. The second matters more.

| # | Test | Calls | Pass |
|---|---|---|---|
| 4.1 | Message a connection | `send_message(target, text)` | server-side acknowledgement, not UI; message visible in `get_conversation`; `outreach.events` row written |
| 4.2 | Message a non-connection | same, target not connected | clean `cannot_message`-type status, nothing sent |
| 4.3 | Connect, Connect-primary, no note | `connect_with_person(target)` | invite dialog opened and submitted; `connection_state` becomes pending on re-read |
| 4.4 | Connect with note | `connect_with_person(target, note=…)` | note delivered; if account has no note credits, `note_limit` reported and the invite still goes or is withheld as configured |
| 4.5 | Connect, Follow-primary | target whose primary button is Follow | goes via More menu or custom-invite deeplink; `submitted: true`; pending on re-read (regression of 6852d49) |
| 4.6 | Connect, truly unavailable | target with Connect disabled (already pending, or restricted) | `connect_unavailable`, no navigation to deeplink, nothing sent |
| 4.7 | Already connected | `connect_with_person` on a 1st-degree | `already_connected`, nothing sent |
| 4.8 | React | `react_to_post(url)` with confirm | reaction visible on re-read; `reaction_unconfirmed` never returned on a successful like (e494d70) |
| 4.9 | Comment | `comment_on_post(url, text)` | `commented: true` only after the thread shows the text; `comment_unconfirmed` otherwise (2661d3f) |
| 4.10 | Threaded reply | reply to an existing comment | lands under the right parent |
| 4.11 | Post | `create_post(text)` ×3 in a row | all three publish; no `composer_unavailable` (fbc37a0) |
| 4.12 | Chat overlay in the way | open a message overlay then `connect_with_person` | invite still completes (upstream 411b68f) |
| 4.13 | Idempotency | repeat 4.1 same day | second send blocked by dedupe_key, not sent twice |
| 4.14 | Confirm gating | any write with `confirm` absent/false | nothing sent, status says confirmation required |

## Tier 5 — Robustness

| # | Test | Calls | Pass |
|---|---|---|---|
| 5.1 | Locale | set LinkedIn UI to German, run 1.1, 4.6, 4.7 | connection-state classification unchanged (extractor.py L159 false positive is the known risk) |
| 5.2 | Soft rate limit | 20 rapid profile reads | `_RATE_LIMITED_MSG` sentinel surfaces, server stays up, next call after 60s succeeds |
| 5.3 | Restricted account | (only if it ever happens) | server stops and reports, never loops login (upstream a996e9f) |
| 5.4 | 2FA during `--login` | run `--login` on a fresh profile | browser stays open until `li_at` cookie exists (d90134c) |
| 5.5 | Unknown section | `get_person_profile(sections="nonsense")` | `unknown_sections: ["nonsense"]`, other sections unaffected |
| 5.6 | Concurrency | two tool calls fired together | serialised; second waits; neither errors |

## Where we have failed before (regression list)

Each of these bit us live. Every one maps to a test above.

1. Connect refused on Follow-primary and creator-mode profiles because the pre-check looked for an anchor that only exists on Connect-primary profiles. Fixed 6852d49. → 4.5
2. The connect fix existed but wasn't on the branch the server ran; 30 minutes lost mid-outreach. Process failure, not code. → 0.9 and the rule: one branch, `main`.
3. A DNS blip was treated as an expired session and quarantined the login. Fixed e2afca3. → 0.8
4. `--login` closed the browser before 2FA finished and exported a half-baked session. Fixed d90134c. → 5.4
5. `create_post` raced React hydration and reported the composer missing. Fixed fbc37a0. → 4.11
6. `comment_on_post` reported success on click, not on publish. Fixed 2661d3f. → 4.9
7. `get_post_comments` credited an @mentioned person as the commenter. Fixed 2661d3f. → 1.4
8. `react_to_post` said unconfirmed when the like had applied, because the permalink layout drops `aria-pressed`. Fixed e494d70. → 4.8
9. Comment submit button not found on the permalink layout. Fixed e494d70. → 4.9
10. German locale produced a false "incoming request" connection state. Known, guarded by comment. → 5.1
11. Warehouse username match was substring-based ("bob" matched "bobby-smith") and the lookup could stall ~100s. Fixed a104fad. → 0.7
12. PyPI reinstall silently dropped the fork's tools. Operational. → 0.9
13. Upstream, not yet hit here: flagged profile URLs rejected by `send_message` (#1214); "Press Enter to Send" preference misreported (#1109); sends confirmed from UI not server (#1108). → 4.1, 4.2

## Known stale tests to fix before trusting the suite

`tests/test_scraping.py::TestConnectWithPerson` has 3 failures: `test_follow_only_after_more_does_not_send`, `test_follow_only_with_note_reports_note_limit_from_deeplink_probe`, `test_more_menu_unavailable_does_not_send`. They assert the old pre-gate behaviour that 6852d49 intentionally removed. Rewrite them so `_submit_invite_dialog` is mocked to return `(False, False, None)` and assert `submitted == False`, nothing sent, and the note-limit path. The real safety property now is "no dialog opened means nothing was sent".

## Sacrificial targets (⚠ Ram to fill)

| Role | Profile | Notes |
|---|---|---|
| Connect-primary, not connected | | for 4.3, 4.4 |
| Follow-primary, not connected | | for 4.5 |
| Already pending | | for 4.6 |
| 1st-degree, consenting | | for 4.1, 4.7, 4.8, 4.9, 4.10 |
| Public creator (read-only) | | for 1.6 |
| Sparse profile (read-only) | | for 1.7, 2.7 |
| Company slug, >50 staff | | for tier 3 |
