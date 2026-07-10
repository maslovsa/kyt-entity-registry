import httpx

from scripts.enrich_from_brandfetch import fetch


def test_domain_with_leading_h_t_p_s_not_mangled(monkeypatch):
    """Regression: `.lstrip("https://")` strips characters in that set,
    not the literal prefix, so domains starting with h/t/p/s used to
    get truncated (e.g. "tether.to" -> "ether.to")."""
    seen = {}

    def fake_get(self, url, *a, **kw):
        seen["url"] = url
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    cases = {
        "tether.to": "/tether.to",
        "stake.com": "/stake.com",
        "https://foo.com/": "/foo.com",
        "http://bar.io": "/bar.io",
    }
    for domain, expected in cases.items():
        seen.clear()
        fetch(domain)
        assert expected in seen["url"], f"{domain} -> {seen['url']}"
