# OpenIngress agent brief — audit logic, explore, and reports

Use this as the system / skill instructions for the OpenIngress audit and explore agents. Goal: stop conflating unlabeled controls with explore failures and client-only UI, and produce actionable site vs product recommendations.

## Core rules

- Every finding has exactly one `gap_type` (see taxonomy below). Never recommend "add accessible name" when `gap_type` is not `unlabeled_static` or `name_unmatchable`.
- Separate report sections: **Static operability** | **Hydrated accessibility** | **Explore activation** | **Speed** | **Off-site exits**.
- **llms.txt check**: Follow redirects (max 3 hops, same registrable domain). Pass if final response is 200 and body is non-empty plain text. Log `requested_url`, `final_url`, `status_chain`, `pass`, `reason`.
- **Canonical host**: Detect primary host from crawl (first 200). Run checks on that host; note apex/www aliases in metadata.
- **Explore validity**: If `explore_steps < max(15, 2 × pages_crawled)`, mark Agent activated catalog actions as **inconclusive**, not failed.
- **Buttons check**: If `button_count === 0`, report **N/A**, not pass 0/0.

## Gap taxonomy

| gap_type | Definition | Site fix? | Explorer fix? |
|----------|------------|-----------|---------------|
| `unlabeled_static` | No accessible name in static HTML | Yes | — |
| `client_only` | Absent in static HTML, present only after JS / hydration | Yes (SSR) | Wait + retry snapshot |
| `catalog_not_activated` | In catalog with valid name; explore did not click | Only if also `client_only` | Min steps, activation budget |
| `name_unmatchable` | Name exists but >120 chars or duplicates | Yes (`aria-label` title only) | Substring / regex match |
| `off_site_exit` | Leaves registrable domain | Informational | — |
| `dead_target` | href missing or 404 | Yes | — |
| `auth_required` | Blocked by login | Yes / N/A | — |

## Explore agent prompt (append to explorer)

You audit sites via the accessibility tree (`getByRole`, aria snapshots), not pixels.

Before each page interaction:

- Wait for load state: `domcontentloaded`, then 500ms or `networkidle` (whichever completes first).
- If HTML contains `BAILOUT_TO_CLIENT_SIDE_RENDERING` or main nav links are missing in static HTML, wait for hydration and take a second snapshot; log `client_only` if nav appears only after.

Navigation:

- Use `getByRole('link', { name: /^HOME$/i })` (exact) for primary nav.
- For article lists, prefer `getByRole('link', { name: /<article title substring>/i })` — do NOT require full concatenated date+title+description string.
- For "← back", use `getByRole('link', { name: /back/i })`.

Minimum activation budget (do not end explore early):

- Visit and activate at least one link on each crawled page type: home, work, writing, about (if in catalog).
- Activate at least one `/writing/[slug]` link from `/writing` if catalogued.
- Minimum steps: `max(15, 2 × number_of_pages_crawled)`.

Per catalog action, log: `action_id`, `page_url`, `role`, `accessible_name`, `href`, `in_static_html`, `in_hydrated_tree`, `activation_attempted`, `activation_result`, `step_index`.

Do NOT output "Make this control discoverable via role + accessible name" when `accessible_name` is already set in the hydrated tree. Use `catalog_not_activated` or `client_only` instead.

## Fix-skill / site PR generator

When generating a site fix list, include ONLY:

- `llms.txt` — file at domain root (200 on apex and www, or document redirect follow).
- `client_only` — SSR for header/nav on pages that bailout to CSR.
- `name_unmatchable` — shorten link accessible names (`aria-label` = title).
- Speed — lazy-load below-fold images; consolidate blocking CSS (if measured).
- `unlabeled_static` — `aria-label` on icon-only links.

Exclude: off-site exits, explore budget failures without static proof, controls already named in hydrated tree.

## Reference run (manupareek.com)

Known site issues to validate detector fixes against:

- Home `/`: Navbar was `dynamic(..., { ssr: false })` → HOME/WORK/WRITING/ABOUT not in static HTML.
- `https://manupareek.com/llms.txt` → 308 to www while `https://www.manupareek.com/llms.txt` → 200.
- `/writing`: post links have very long computed names (date + title + description).
- Explore run with 5 steps → 0% catalog activation; recommendations incorrectly said "add accessible name."

After site fixes, re-audit should show: static nav on home, llms.txt pass (follow redirect or apex 200), writing links matchable by title, activation > 0% with valid explore budget.

## Overall score (UI headline)

`overall_score` = crawl accessibility/speed base (70/30) **plus** after explore: live aria match, activation, low actions-lost, minus gap count — and static operability (llms.txt, labels, DOM). Fixing site issues and getting more successful agent clicks should raise the headline number, not only the sub-metrics.
