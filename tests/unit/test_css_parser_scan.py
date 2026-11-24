"""The stylesheet parser and fetch deadline: robustness against hostile or malformed input."""

import http.server
import threading
import time

import pytest

from open_deep_research.scan_cli import css_rules, fetch, hiding_selectors


def test_rules_and_nested_at_blocks():
    css = """/* c */ .a{display:none} @media (min-width:1px){ .b{display:none} @supports (x){ .c{display:none} } }
    @container (min-width: 1px) { .cq{display:none} }
    @keyframes k { 0% { opacity:0 } 100% { opacity:1 } } .d { color: red } @import url(x.css); .e{visibility:hidden}"""
    assert [sel for sel, _ in css_rules(css)] == [".a", ".d", ".e"]
    assert [t[1] for t in hiding_selectors(css)] == [{"a"}, {"e"}]


def test_layer_and_supports_blocks_are_read():
    css = "@layer base { .sr-only{clip:rect(0 0 0 0)} @media print { .p{display:none} } } @supports (display:grid) { .g{display:none} }"
    assert [sel for sel, _ in css_rules(css)] == [".sr-only", ".g"]


def test_unbalanced_braces_do_not_derail_later_rules():
    assert [s for s, _ in css_rules("} } .x{display:none} @media{ .y{ } .z{display:none")] == [".x"]
    assert [s for s, _ in css_rules(".p{a:b}} .q{display:none}")] == [".p", ".q"]


def test_pathological_stylesheet_parses_quickly():
    # Long brace-free runs between unbalanced braces made the earlier regex version quadratic.
    css = ("@keyframes k { 0% { opacity:0 } " + "a" * 2000 + " { " + "b" * 2000 + " ") * 100
    start = time.monotonic()
    css_rules(css)
    hiding_selectors(css + " .h{display:none}")
    assert time.monotonic() - start < 2.0


class _Drip(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/css")
        self.end_headers()
        try:
            for _ in range(100):
                self.wfile.write(b"a")
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass

    def log_message(self, *args):
        pass


def test_fetch_gives_up_on_a_slow_drip_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Drip)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            fetch(f"http://127.0.0.1:{server.server_port}/s.css", timeout=0.3)
        assert time.monotonic() - start < 3
    finally:
        server.shutdown()


def test_deeply_nested_blocks_do_not_recurse_without_limit():
    css = "@supports (a) { " * 5000 + ".x{display:none}" + " }" * 5000 + " .y{display:none}"
    assert [sel for sel, _ in css_rules(css)] == [".y"]


def test_braces_inside_strings_are_ignored():
    css = '.icon:before{content:"{"} .q:after{content:"\\"}"} .w{content:\'}\'} .sr-only{clip:rect(0 0 0 0)}'
    assert [sel for sel, _ in css_rules(css)] == [".icon:before", ".q:after", ".w", ".sr-only"]


def test_escaped_quotes_and_braces_in_selectors():
    css = r".\[font\:\'A\'\]{font-family:A} .\{x\}{color:red} .h{display:none}"
    assert [sel for sel, _ in css_rules(css)] == [r".\[font\:\'A\'\]", r".\{x\}", ".h"]
