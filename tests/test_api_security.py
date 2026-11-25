"""The local API must only answer Nib's own page, not other web sites open in the browser.

Run with:  python -m pytest tests
"""
import http.client
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server as S  # noqa: E402


@pytest.fixture(scope="module")
def srv():
    s = S.make_server(0)                       # free port
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s.server_address[1]
    s.shutdown()


def req(port, method, path, body=None, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{port}"}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data, r


def own(port, **extra):
    return {"X-Nib-Token": S.TOKEN, "Origin": f"http://127.0.0.1:{port}", **extra}


JSON = {"Content-Type": "application/json"}


def test_index_carries_token_and_no_framing(srv):
    st, data, r = req(srv, "GET", "/")
    assert st == 200
    assert S.TOKEN.encode() in data and S.TOKEN_PLACEHOLDER not in data
    assert r.getheader("X-Frame-Options") == "DENY"


def test_own_page_works(srv):
    st, data, _ = req(srv, "GET", "/api/settings", headers={"X-Nib-Token": S.TOKEN})
    assert st == 200 and "machine" in json.loads(data)
    st, data, _ = req(srv, "GET", "/api/status?log=0", headers={"X-Nib-Token": S.TOKEN})
    assert st == 200 and "machine" in json.loads(data)
    st, data, _ = req(srv, "POST", "/api/disconnect", b"{}", own(srv, **JSON))
    assert st == 200 and json.loads(data) == {"ok": True}
    # also reachable as localhost
    st, _, _ = req(srv, "POST", "/api/disconnect", b"{}",
                   {"X-Nib-Token": S.TOKEN, "Origin": f"http://localhost:{srv}", **JSON},
                   host=f"localhost:{srv}")
    assert st == 200


def test_beacon_token_in_query(srv):
    st, _, _ = req(srv, "POST", f"/api/bye?token={S.TOKEN}", b"{}",
                   {"Origin": f"http://127.0.0.1:{srv}", **JSON})
    assert st == 200


def test_foreign_site_without_token_blocked(srv):
    # what fetch(..., {mode: "no-cors"}) from another web site sends
    st, _, _ = req(srv, "POST", "/api/command", b'{"gcode": "G1 X100"}',
                   {"Origin": "https://evil.example", "Content-Type": "text/plain;charset=UTF-8"})
    assert st == 403


def test_foreign_origin_blocked_even_with_token(srv):
    st, _, _ = req(srv, "POST", "/api/disconnect", b"{}",
                   {"X-Nib-Token": S.TOKEN, "Origin": "https://evil.example", **JSON})
    assert st == 403


def test_other_local_port_blocked(srv):
    st, _, _ = req(srv, "POST", "/api/disconnect", b"{}",
                   {"X-Nib-Token": S.TOKEN, "Origin": "http://127.0.0.1:1", **JSON})
    assert st == 403


def test_wrong_token_blocked(srv):
    st, _, _ = req(srv, "GET", "/api/settings", headers={"X-Nib-Token": "nope"})
    assert st == 403
    st, _, _ = req(srv, "GET", "/api/settings")
    assert st == 403


def test_dns_rebinding_blocked(srv):
    # a foreign domain resolving to 127.0.0.1 must not even get the page (it holds the token)
    st, data, _ = req(srv, "GET", "/", host="evil.example")
    assert st == 403 and S.TOKEN.encode() not in data
    st, _, _ = req(srv, "GET", "/api/settings", headers={"X-Nib-Token": S.TOKEN}, host=f"evil.example:{srv}")
    assert st == 403


def test_non_json_post_refused(srv):
    st, _, _ = req(srv, "POST", "/api/disconnect", b"{}",
                   own(srv, **{"Content-Type": "text/plain"}))
    assert st == 415
