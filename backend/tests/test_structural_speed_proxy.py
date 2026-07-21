from app.services.site_audit_analyzer import _speed_assessment
from app.services.variant_html import summarize_variant_html


def test_variant_html_summary_includes_structure_metrics():
    html = """
    <html>
      <body>
        <main>
          <section>
            <div><a href="/docs">Docs</a></div>
            <div><button aria-label="Start trial">Start</button></div>
            <form action="/signup"><input type="submit" value="Create account" /></form>
          </section>
        </main>
      </body>
    </html>
    """

    summary = summarize_variant_html(html)
    structure = summary["structure"]

    assert structure["dom_node_count"] >= 8
    assert structure["max_dom_depth"] >= 4
    assert structure["interactive_node_count"] >= 3
    assert structure["interactive_density_percent"] > 0
    assert structure["text_char_count"] > 0


def test_speed_assessment_penalizes_heavy_dense_structure():
    repeated_cards = "".join(
        f'<article><h2>Plan {i}</h2><p>{"copy " * 80}</p><a href="/cta/{i}">Choose</a><button>More</button></article>'
        for i in range(80)
    )
    scripts = "".join("<script>console.log('x')</script>" for _ in range(22))
    styles = "".join('<link rel="stylesheet" href="/app.css" />' for _ in range(10))
    images = "".join('<img src="/hero.png" alt="hero" />' for _ in range(40))
    html = f"<html><body><main><section>{styles}{scripts}{images}{repeated_cards}</section></main></body></html>"

    summary, findings = _speed_assessment(
        imported={"pages": [{"html": html, "metadata": {"summary": summarize_variant_html(html)}}]},
        graph={"actions": [{"target_kind": "unknown_js"} for _ in range(4)], "pages": [{"id": "home"}]},
        html=html,
    )

    assert summary["score"] < 60
    assert summary["dom_node_count"] > 400
    assert summary["interactive_node_count"] > 100
    assert summary["interactive_density_percent"] > 12
    assert any("DOM" in item or "interactive" in item.lower() for item in findings)


def test_speed_assessment_keeps_small_simple_page_at_full_score():
    html = "<html><body><main><h1>Example</h1><p>Hello world.</p><a href='https://iana.org'>Learn more</a></main></body></html>"

    summary, findings = _speed_assessment(
        imported={"pages": [{"html": html, "metadata": {"summary": summarize_variant_html(html)}}]},
        graph={"actions": [{"target_kind": "external_exit"}], "pages": [{"id": "home"}]},
        html=html,
    )

    assert summary["score"] == 100.0
    assert summary["dom_node_count"] > 0
    assert summary["interactive_node_count"] == 1
    assert findings == [
        "Structural speed posture looks lightweight for agent browsing; the initial page is small, shallow, and low-friction."
    ]
