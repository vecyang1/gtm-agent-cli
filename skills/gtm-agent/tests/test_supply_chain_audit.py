#!/usr/bin/env python3
"""
test_supply_chain_audit.py - Unit tests for Web Supply Chain & Third-Party Script Security Audit
"""

import unittest
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from portfolio_gtm_audit import (
    HIJACKED_OR_DEPRECATED_DOMAINS,
    APPROVED_VENDOR_DOMAINS,
    extract_domains_from_html,
    ContainerAuditResult,
)


class TestSupplyChainSecurityAudit(unittest.TestCase):

    def test_extract_domains_script_src(self):
        html = '<script async src="https://cdn.taku.cool/js/latest.js"></script>'
        domains = extract_domains_from_html(html)
        self.assertIn("cdn.taku.cool", domains)

    def test_extract_domains_inline_js_urls(self):
        html = '''
        <script>
            var s = document.createElement("script");
            s.src = "https://cdn.taku-app.com/js/latest.js";
            document.head.appendChild(s);
        </script>
        '''
        domains = extract_domains_from_html(html)
        self.assertIn("cdn.taku-app.com", domains)

    def test_extract_domains_protocol_relative(self):
        html = '<script src="//visitor.leadsourcing.co/n?tid=123"></script>'
        domains = extract_domains_from_html(html)
        self.assertIn("visitor.leadsourcing.co", domains)

    def test_hijacked_domain_detection(self):
        html_hijacked = '<script src="https://cdn.taku-app.com/js/latest.js"></script>'
        domains = extract_domains_from_html(html_hijacked)
        hijacked = [d for d in domains if any(bad in d for bad in HIJACKED_OR_DEPRECATED_DOMAINS)]
        self.assertIn("cdn.taku-app.com", hijacked)

    def test_approved_partner_domain(self):
        html_safe = '<script src="https://cdn.taku.cool/js/latest.js"></script>'
        domains = extract_domains_from_html(html_safe)
        safe = [d for d in domains if any(d == app or d.endswith("." + app) for app in APPROVED_VENDOR_DOMAINS)]
        self.assertIn("cdn.taku.cool", safe)


if __name__ == "__main__":
    unittest.main()
