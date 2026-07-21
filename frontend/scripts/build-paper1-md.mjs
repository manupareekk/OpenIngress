import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const out = join(__dirname, '../src/data/research/paper1AgentBlindWeb.md')

// Verbatim paper body from Notebook LM export — do not edit prose.
const md = String.raw`#### Executive Summary
The transition of the global internet from a human-centric viewing medium to an autonomous machine-to-machine transactional environment is severely bottlenecked. While **51% of all global web traffic is now programmatically driven** by automated entities, bots, and AI agents, the public web remains structurally hostile to automated navigation. 

An analysis of top-tier commercial domains reveals that **88.4% of websites immediately block agent navigation paths on the very first session**. This deficit is not identified by traditional compliance scans. While organizations rely on automated accessibility scoring engines to validate their digital presence, these evaluations act as syntax linters rather than testing interactive machine operability, capturing only 30% to 40% of true barriers. The stakes of this failure are enormous: we are rapidly moving from an "attention economy" to an "answer economy," where 26% of users end their search session immediately after reading an AI-generated answer. 

As the digital economy shifts from visual search indexing to autonomous task delegation via Answer Engine Optimization (AEO), brands that fail to align their document structures with native browser serialization layers risk total exclusion from the automated transaction stream.

<!-- chart: exec-stats -->

#### What "Agent-Accessible" Means (Tree, Not Pixels)
When AI agents navigate the web, they do not "see" the website the way humans do. Currently, the architecture of browser agents falls into three distinct perception categories, each with its own advantages and critical limitations:

**1. Vision-Based Perception (Pixels)**
Some agents attempt to use multimodal vision models to process a screenshot of the browser viewport and return $(x,y)$ coordinates to execute clicks. While this provides universal coverage for any interface a human can see (including \`<canvas>\` rendered apps, PDFs, and remote desktops), it is incredibly computationally expensive and fragile. Multi-modal screenshots demand massive token allotments—often burning through tens of thousands of tokens for a single multi-step session. Furthermore, vision agents suffer from high resolution sensitivity and "state opacity"; they can only infer underlying element states (like hidden form fields or dynamic ARIA changes) from surface-level pixels, which frequently leads to silent failures.

**2. Accessibility-Tree Perception (AXTree)**
To bypass the noise of the raw Document Object Model (DOM), which routinely overwhelms context windows with over 15,000 tokens of nested \`<div>\` tags, trackers, and inline styles, the industry has converged on the **Accessibility Tree (AXTree)**. This engine-level abstraction is generated directly by the browser and strips away visual styling, leaving only semantically meaningful elements. It reduces the token payload by approximately 93%, generating a highly efficient representation of 200–400 tokens. 

For a site to be "agent-accessible" in this paradigm, its interactive elements must be properly serialized with four core properties:
*   **Role:** What the element is (e.g., \`button\`, \`link\`, \`checkbox\`).
*   **Name:** The accessible label the agent "reads".
*   **State:** The current condition (e.g., \`focused\`, \`checked\`, \`expanded\`).
*   **Description:** Additional metadata for context (e.g., \`aria-describedby\`).

Major frameworks like Microsoft's Playwright MCP, Anthropic's Computer Use, and browser-use rely heavily on this tree. If an interface is built using unsemantic HTML without ARIA attributes, it is literally invisible to these agents.

**3. Runtime Structural Perception**
A newer approach relies on capturing the live, compressed DOM via a browser extension running in the user's authenticated session. This approach avoids bot-detection systems by acting as a peripheral to the user's browser, allowing it to navigate legacy enterprise UIs and jQuery-era admin panels that fail to expose a rich accessibility tree.

<!-- chart: token-reduction -->

#### Methodology: Crawl + Tree Walk vs. Human Visual Audit
Traditional accessibility audits typically rely on visual inspection or automated scanners like Lighthouse and axe-core. However, these tools are fundamentally limited; research demonstrates they detect only 30% to 40% of actual accessibility issues. They can verify that an image has \`alt\` text or that contrast ratios are met, but they cannot assess contextual appropriateness, the logic of keyboard navigation focus order, or the execution of complex Single Page Application (SPA) state changes.

To systematically diagnose discrepancies between visual and machine operability, the OpenIngress pipeline performs an automated crawl paired with a recursive accessibility tree-walk. This process perfectly mimics the cognitive loop of a browser-based AI agent, uncovering dynamic ID mutations and missing focus traps that visual audits entirely miss. 

Furthermore, new methodologies are emerging to track agent readiness. Google's Lighthouse 13.3 has introduced a dedicated **Agentic Browsing** category. This evaluates WebMCP integration, the presence of \`llms.txt\` files for AI discoverability, Layout Stability (since Cumulative Layout Shift breaks agent interactions), and verifies that the accessibility tree is well-formed. Meanwhile, academic benchmarks like Online-Mind2Web evaluate agent trajectories across real-world sites using multi-phase protocols. Their findings show that while top-tier models (like the Operator agent) achieve a 61.3% success rate, most agents cluster around 28–30% due to deep compositional constraints on the live web. 

<!-- chart: detection-gap -->
<!-- chart: agent-benchmarks -->

#### Findings by Vertical (E-Commerce, SaaS, Media)
A massive evaluation of the top 1,000,000 home pages reveals a web that is increasingly complex and deeply hostile to automated systems. The average home page complexity has surged to **1,437 distinct elements**, a 22.5% increase in a single year. As a result, 95.9% of home pages currently have detectable WCAG 2 conformance failures.

*   **Top E-Commerce:** E-commerce domains present a highly dense, transaction-limiting environment. WebAIM 2026 data shows that popular platforms like Shopify average 75.1 errors per page, and Magento averages 75.8 errors. The primary blocker is unlabelled form fields, particularly within checkout operations. Across the web, **51% of home pages have missing form input labels**. Furthermore, within the Online-Mind2Web benchmark, filter and sort operations account for 57.7% of major agent failures. When an agent cannot reliably label a credit card input or sort an inventory grid, the transaction fails entirely.
*   **Top SaaS Sites:** SaaS and B2B platforms heavily rely on client-rendered interactions. These sites deploy massive amounts of JavaScript libraries; unfortunately, the use of popular libraries (like jQuery, React, and Swiper) consistently correlates with an increase in detected accessibility errors. The dominant failure in this sector is client-rendered pricing cards with unlabelled state toggles. Because custom billing switches lack native HTML checkbox or radio roles, agents cannot confirm the active pricing tier and frequently abort the task.
*   **Media, Content & Information Services:** Publishing portals average over 59.2 errors per home page. The absolute point of failure here is dynamic ad injection. Ad networks heavily degrade accessibility—sites using Google AdSense, Taboola, or Criteo display significantly more errors on average. These injections generate high Cumulative Layout Shifts (CLS), which causes untracked node mutations that invalidate the AI agent's active page graph and trigger task abandonment.

<!-- chart: vertical-errors -->
<!-- chart: web-scale -->

#### Top 10 Failure Patterns
The OpenIngress taxonomy identifies the dominant agent blockers across the web, categorized into three operational groups:

**Perception Gaps (Invisible to the agent)**
1.  **Unlabelled Interactive Controls:** Buttons or links using only visual SVG icons. WebAIM reports that **46.3% of home pages contain empty links, and 30.6% have empty buttons**. Agents see \`button ""\` and bypass the control.
2.  **Dynamic Selector ID Mutation:** Enterprise apps (e.g., Salesforce, SAP) dynamically regenerate element IDs (like \`__rg-1::42\`) on every load. Simple ID targeting breaks instantly; agents must rely on role and parent-path matching.
3.  **Unlabeled Image Links:** Over 16.2% of all home page images miss alternative text, and 45% of these are linked images. Without an accessible name, the link's destination is completely opaque to the agent.
4.  **Misused ARIA Injections:** Developers frequently inject complex ARIA attributes instead of using native semantic HTML. In 2026, **the average home page contained 133 ARIA attributes**, a 27% increase in just one year. Alarmingly, pages with ARIA present average 59.1 errors, compared to just 42 errors on pages without it. Poorly configured ARIA actively damages the accessibility tree, confusing both screen readers and AI agents.

<!-- chart: failure-prevalence -->

**Cognitive Gaps (Confusing to the agent)**
5.  **SPA State & Route Desynchronization:** Client-side frameworks update the visual interface without pushing corresponding focus or status updates to the AXTree, leaving agents operating on stale data.
6.  **Visual-Only Form Field Validation:** Error states indicated solely by a red CSS border or unassociated text nodes. Because the error is not programmatically linked via \`aria-describedby\`, agents get stuck in infinite loops attempting to submit invalid form data.
7.  **Unlabeled Option & Billing Swappers:** Custom JS toggles lacking native semantics. If a monthly/annual billing switch cannot be parsed programmatically, agents cannot proceed with financial confidence.

<!-- chart: aria-errors -->

**Action Gaps (Un-actionable by the agent)**
8.  **Dead-End Modals & Missing Focus Traps:** Dialog overlays that open without trapping the keyboard focus. Agents continue sending sequential input commands to the obscured background DOM, trapping them in navigational loops.
9.  **Unsemantic Click Targets:** Critical checkout triggers built using flat \`<div>\` elements bound to JavaScript click listeners. Because they lack interactive roles, they are excluded from the AXTree's interactive collection.
10. **Intrusive Cookie Walls & Unsynchronized Visibility:** Third-party cookie consent banners with flat hierarchies lock the viewport. While some compliance tools like OneTrust correlate with fewer overall page errors, tracking scripts like FingerprintJS result in an average of 112.4 errors, severely degrading the operability of the site. Furthermore, hidden elements remaining active in the AXTree trick agents into interacting with invisible nodes.

#### Implications for Brands
Digital survival in the autonomous economy demands a complete realignment. We are experiencing the "Responsive Design Moment for AI Agents". For decades, digital marketing relied on a visual-first paradigm designed to attract human eyes. Today, AI agents are performing search, comparison, and transactions, and they do not care about high-resolution visual branding—they care purely about semantic utility.

The shift to AEO (Answer Engine Optimization) means that optimizing to become the source cited by LLMs is now critical. Search traffic is transforming; 26% of users now end their session directly on the AI summary without ever visiting the source site. Traditional SEO focused on PageRank, but AI engines prioritize branded mentions, FAQ-formatted structures, and explicit entity authority. 

Brands must adapt their content distribution layers. For instance, platforms like Sentry utilize content negotiation to serve structured Markdown instead of HTML specifically for AI agents, reducing token payload by over 80%. Adopting clean semantic HTML, implementing structured JSON-LD, and ensuring content is available via Server-Side Rendering (SSR) are no longer optional best practices—they are the foundational infrastructure required to remain visible in the answer economy.

#### Limits & Future Work
While structuring applications for the AXTree dramatically improves agent operability, there are ongoing architectural limitations and emerging standards that will redefine web automation:

*   **The WebMCP Standard:** The Model Context Protocol for the Web (WebMCP) is an emerging W3C standard designed to expose structured tools directly to AI agents. Using either a declarative HTML API (e.g., adding \`toolname\` attributes to forms) or an imperative JavaScript API, websites can explicitly define their action capabilities. However, this standard is currently highly controversial. Critics argue that WebMCP introduces a redundant layer that parallels the existing accessibility tree, leading to desynchronization and giving developers an excuse to abandon true accessibility for human users. Proponents counter that the AXTree suffers from deep platform bugs (like missing canvas UI mappings in Electron) and that WebMCP provides the explicit, deterministic action schemas agents need.
*   **The Power of Command Line Interfaces (CLIs):** To counter the heavy context window tax of traditional agent frameworks, tools like Vercel's \`agent-browser\` have demonstrated that simple Rust-based CLIs connecting directly via Chrome DevTools Protocol (CDP) can achieve a **94% token reduction** over heavy frameworks like Playwright MCP. By relying on accessibility "snapshots and refs" rather than full DOM dumps, the agent operates faster and more reliably.
*   **API-Based Web Agents:** Where traditional GUIs fail entirely, the most robust fallback is direct API integration. Research comparing agent performance shows that when agents are granted direct access to comprehensive, well-documented backend APIs, success rates soar. For example, platforms with robust API ecosystems like Gitlab (988 endpoints) support highly successful agent task completion, whereas platforms with poor API support (like Reddit, with 31 endpoints) force the agent to fall back on fragile web browsing. The absolute state of the art is the **Hybrid Agent**, which dynamically interleaves structured API calls with accessibility-tree web browsing, achieving a 38.9% success rate on complex benchmarks (a full 24% improvement over standard browsing agents).

Future research and enterprise development must focus on bridging these modalities. Integrating \`llms.txt\` for fast discovery, leveraging \`agents.json\` to declare capabilities, and hybridizing AXTree navigation with direct API execution will form the backbone of the fully agentic web.
`

writeFileSync(out, md, 'utf8')
console.log('wrote', out, md.length, 'chars')
