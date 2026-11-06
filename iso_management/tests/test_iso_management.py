from odoo.tests import TransactionCase, tagged

from ..models.iso_catalog import CLAUSES
from ..models.iso_rules import RULES


@tagged("post_install", "-at_install")
class TestIsoManagement(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["iso.management.standard"].seed_catalog()
        self.standard = self.env["iso.management.standard"].search([("company_id", "=", self.env.company.id)], limit=1)

    def test_catalog_matches_iso_14001_2015(self):
        numbers = [row[0] for row in CLAUSES]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertNotIn("3.1.1", numbers)
        titles = dict((row[0], row[1]) for row in CLAUSES)
        self.assertEqual(titles["10.2"], "Nonconformity and corrective action")
        self.assertEqual(titles["10.3"], "Continual improvement")
        self.assertEqual(titles["9.2.2"], "Internal audit programme")
        self.assertEqual(set(self.standard.clause_ids.mapped("clause_number")), set(numbers))
        self.assertEqual(set(self.standard.clause_ids.mapped("edition")), {"2015"})

    def test_hierarchy(self):
        clause = self.standard.clause_ids.filtered(lambda c: c.clause_number == "6.1.2")
        self.assertEqual(clause.parent_id.clause_number, "6.1")

    def test_rules_only_reference_catalog_clauses(self):
        numbers = {row[0] for row in CLAUSES}
        self.assertFalse(set(RULES) - numbers)

    def _run(self, number, provider="rules"):
        clause = self.standard.clause_ids.filtered(lambda c: c.clause_number == number)
        scan = self.env["iso.management.scan"].create({
            "clause_id": clause.id, "company_id": clause.company_id.id, "provider": provider,
            "execution_state": "running", "detector_version": "3",
        })
        scan._run_detection()
        scan.execution_state = "done"
        return clause, scan

    def test_rule_maps_real_records(self):
        from odoo import fields
        self.env["calendar.event"].create({
            "name": "Internal audit 2026 - warehouse", "start": fields.Datetime.now(),
            "stop": fields.Datetime.now(),
        })
        clause, scan = self._run("9.2.1")
        matches = scan.evidence_ids.filtered(lambda e: e.evidence_type == "rule_match")
        self.assertTrue(matches)
        self.assertEqual(matches[0].source_model, "calendar.event")
        self.assertEqual(matches[0].provider, "rules")
        self.assertEqual(matches[0].rule_strength, "direct")
        self.assertEqual(clause.coverage_status, "covered")

    def test_clause_without_rule_is_a_gap_not_a_coincidence(self):
        clause, scan = self._run("4.1")
        self.assertFalse(scan.evidence_ids.filtered(lambda e: e.evidence_type == "rule_match"))
        self.assertTrue(scan.evidence_ids.filtered(lambda e: e.evidence_type == "gap"))
        self.assertEqual(clause.coverage_status, "gap")

    def test_graph_data_is_consistent(self):
        self._run("5.3")
        data = self.env["iso.management.standard"].get_graph_data(self.standard.id)
        ids = {node["id"] for node in data["nodes"]}
        for link in data["links"]:
            self.assertIn(link["source"], ids)
            self.assertIn(link["target"], ids)
        self.assertEqual(sum(data["summary"].values()), len([c for c in self.standard.clause_ids if not c.child_ids]))

    def test_rag_requires_configuration(self):
        from odoo.exceptions import UserError
        from ..models import iso_providers
        if iso_providers.rag_status()[0]:
            self.skipTest("RAG is configured in this environment")
        with self.assertRaises(UserError):
            self.standard.clause_ids[:1].action_run_rag_detection()
