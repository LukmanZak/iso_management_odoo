"""Clause management and conservative, cross-app evidence discovery."""

import html
import base64
import binascii
from datetime import timedelta
import logging
import re
import uuid
from collections import defaultdict

import psycopg2
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

SENSITIVE_MODEL_PREFIXES = (
    "attendance.face.",
    "auth.",
    "bus.",
    "digest.",
    "hr.attendance",
    "hr.employee",
    "hr.job",
    "hr.resume.",
    "ir.",
    "mail.",
    "res.",
    "resource.",
    "res.device.log",
    "res.partner.bank",
    "res.users",
    "iso.management.",
)
SENSITIVE_MODELS = {
    "res.partner",
    "ir.config_parameter",
    "ir.cron",
    "ir.logging",
    "ir.model",
    "ir.model.data",
    "ir.model.fields",
}
SENSITIVE_FIELD_PARTS = (
    "address", "avatar", "bank", "face", "embedding", "email", "image",
    "login", "mobile", "password", "phone", "private", "secret", "session",
    "signature",
    "ssn", "street", "token", "user_id", "vat", "zip",
)
PREFERRED_TEXT_FIELDS = (
    "name", "title", "subject", "description", "description_sale",
    "description_purchase", "note", "notes", "comment", "summary",
    "reason", "reference",
)
ENVIRONMENTAL_FIELD_TERMS = (
    "environmental", "carbon", "emission", "waste", "energy", "water",
    "recycl", "pollution", "climate",
)
CONTEXT_MODELS = (
    ("sale.order", "Sales orders"),
    ("purchase.order", "Purchase orders"),
    ("stock.picking", "Inventory transfers"),
    ("stock.move", "Inventory moves"),
    ("product.template", "Products"),
)


class IsoManagementStandard(models.Model):
    _name = "iso.management.standard"
    _description = "ISO Standard Edition"
    _check_company_auto = True

    name = fields.Char(required=True, default="ISO 14001:2015")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    official_url = fields.Char(default="https://www.iso.org/standard/60857.html")
    clause_ids = fields.One2many("iso.management.clause", "standard_id", string="Clauses")
    rag_ready = fields.Boolean(compute="_compute_rag_info", string="RAG ready")
    rag_info = fields.Text(compute="_compute_rag_info", string="RAG & AI status")
    chunk_count = fields.Integer(compute="_compute_rag_info", string="Indexed records")
    covered_count = fields.Integer(compute="_compute_coverage_counts")
    partial_count = fields.Integer(compute="_compute_coverage_counts")
    gap_count = fields.Integer(compute="_compute_coverage_counts")
    unscanned_count = fields.Integer(compute="_compute_coverage_counts")

    @api.depends("company_id")
    def _compute_rag_info(self):
        from .iso_providers import config, rag_status
        cfg = config()
        ready, message, _missing = rag_status()
        for standard in self:
            standard.rag_ready = ready
            standard.chunk_count = self.env["iso.management.chunk"].index_count(standard.company_id.id)
            standard.rag_info = _(
                "Detection provider: %(provider)s\nEmbeddings: %(embed)s (%(dim)s dimensions)\nVector store: pgvector\nLLM: %(llm)s\nIndexed records: %(chunks)s\nStatus: %(status)s",
                provider=_("RAG + AI") if cfg["provider"] == "rag" and ready else _("Curated rules"),
                embed="%s / %s" % (cfg["embed_provider"], cfg["embed_model"]), dim=cfg["embed_dim"],
                llm=cfg["ai_model"], chunks=standard.chunk_count, status=message)

    @api.depends("clause_ids.coverage_status")
    def _compute_coverage_counts(self):
        for standard in self:
            statuses = standard.clause_ids.mapped("coverage_status")
            standard.covered_count = statuses.count("covered")
            standard.partial_count = statuses.count("partial")
            standard.gap_count = statuses.count("gap")
            standard.unscanned_count = statuses.count("unscanned")

    @api.model
    def seed_catalog(self):
        """Idempotently load the ISO 14001:2015 clause catalog for every company."""
        from .iso_catalog import CLAUSES
        Clause = self.env["iso.management.clause"].sudo().with_context(active_test=False)
        Scan = self.env["iso.management.scan"].sudo()
        Standard = self.sudo().with_context(active_test=False)
        valid_numbers = {row[0] for row in CLAUSES}
        for company in self.env["res.company"].sudo().search([]):
            standard = Standard.search([("name", "in", ["ISO 14001:2015", "ISO 14001:2026"]), ("company_id", "=", company.id)], limit=1)
            if not standard:
                standard = Standard.create({"name": "ISO 14001:2015", "company_id": company.id})
            else:
                standard.write({"name": "ISO 14001:2015", "official_url": "https://www.iso.org/standard/60857.html"})
            existing = Clause.search([("standard", "=", "ISO 14001"), ("company_id", "=", company.id)])
            obsolete = existing.filtered(lambda c: c.clause_number not in valid_numbers)
            if obsolete:
                obsolete.write({"parent_id": False})
                obsolete.unlink()
            # Scans produced by the old keyword detector are wrong by design; drop them.
            Scan.search([("company_id", "=", company.id), "|", ("detector_version", "=", False), ("detector_version", "!=", "3")]).unlink()
            by_number = {}
            for sequence, (number, title, summary, keywords) in enumerate(CLAUSES, 1):
                clause = Clause.search([("standard", "=", "ISO 14001"), ("clause_number", "=", number), ("company_id", "=", company.id)], limit=1)
                parent = by_number.get(number.rsplit(".", 1)[0]) if "." in number else False
                values = {
                    "standard_id": standard.id, "parent_id": parent.id if parent else False,
                    "catalog_sequence": sequence, "edition": "2015", "clause_title": title,
                    "clause_summary": summary, "search_keywords": keywords, "active": True,
                }
                if clause:
                    clause.write(values)
                else:
                    values.update({"standard": "ISO 14001", "clause_number": number, "company_id": company.id})
                    clause = Clause.create(values)
                by_number[number] = clause
        return True

    # -- actions ---------------------------------------------------------
    def _leaf_clauses(self):
        self.ensure_one()
        return self.clause_ids.filtered(lambda clause: not clause.child_ids and clause.active)

    def action_run_all(self):
        self.ensure_one()
        scans = self.env["iso.management.scan"]
        for clause in self._leaf_clauses():
            scans |= self.env["iso.management.scan"].browse(clause._queue_scan(self.env["iso.management.scan"]._default_provider())["res_id"])
        return self._scans_action(scans)

    def action_run_all_rag(self):
        self.ensure_one()
        from .iso_providers import rag_status
        ready, message, _missing = rag_status()
        if not ready:
            raise UserError(message)
        scans = self.env["iso.management.scan"]
        for clause in self._leaf_clauses():
            scans |= self.env["iso.management.scan"].browse(clause._queue_scan("rag")["res_id"])
        return self._scans_action(scans)

    def action_reindex(self):
        self.ensure_one()
        count = self.env["iso.management.chunk"].reindex(self.company_id)
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("RAG index"), "message": _("%s record(s) embedded and indexed.", count), "type": "success"},
        }

    def action_open_graph(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client", "tag": "iso_graph", "name": _("ISO Graph"),
            "params": {"standard_id": self.id},
        }

    def _scans_action(self, scans):
        return {
            "type": "ir.actions.act_window", "name": _("Detection runs"),
            "res_model": "iso.management.scan", "view_mode": "list,form",
            "domain": [("id", "in", scans.ids)],
        }

    # -- graph -----------------------------------------------------------
    @api.model
    def get_graph_data(self, standard_id=False):
        standard = self.browse(int(standard_id)).exists() if standard_id else self.search([], limit=1)
        if not standard:
            return {"nodes": [], "links": [], "summary": {}, "standard": False}
        standard.check_access("read")
        clauses = standard.clause_ids
        by_id = {clause.id: clause for clause in clauses}
        children = {}
        for clause in clauses:
            children.setdefault(clause.parent_id.id, []).append(clause)

        def level_of(clause):
            level = 0
            while clause.parent_id:
                clause, level = clause.parent_id, level + 1
            return level

        def leaf_statuses(clause):
            kids = children.get(clause.id)
            if not kids:
                return [clause.coverage_status]
            result = []
            for kid in kids:
                result.extend(leaf_statuses(kid))
            return result

        def aggregate(statuses):
            unique = set(statuses)
            if unique == {"covered"}:
                return "covered"
            if unique <= {"unscanned"}:
                return "unscanned"
            if unique == {"gap"}:
                return "gap"
            return "partial"

        nodes, links = [], []
        module_nodes = {}
        for clause in clauses:
            status = clause.coverage_status if not clause.child_ids else aggregate(leaf_statuses(clause))
            nodes.append({
                "id": "c%s" % clause.id, "type": "clause", "label": clause.clause_number,
                "title": clause.clause_title, "status": status, "level": level_of(clause),
                "is_leaf": not clause.child_ids, "res_model": clause._name, "res_id": clause.id,
                "mapped": clause.mapped_count,
            })
            if clause.parent_id and clause.parent_id.id in by_id:
                links.append({"source": "c%s" % clause.parent_id.id, "target": "c%s" % clause.id, "type": "hierarchy"})
            if clause.child_ids:
                continue
            scan = clause._latest_done_scan()
            for evidence in scan.evidence_ids.filtered(lambda ev: ev.evidence_type == "rule_match"):
                app_key = evidence.source_app or evidence.source_model
                if app_key not in module_nodes:
                    module_nodes[app_key] = {"id": "m%s" % len(module_nodes), "type": "app", "label": app_key, "status": "app", "level": 0}
                nodes.append({
                    "id": "e%s" % evidence.id, "type": "evidence", "label": evidence.source_record_name or evidence.name,
                    "title": evidence.match_reason or "", "status": evidence.rule_strength or "supporting",
                    "score": evidence.relevance_score, "provider": evidence.provider,
                    "res_model": evidence._name, "res_id": evidence.id,
                    "source_model": evidence.source_model, "source_record_id": evidence.source_record_id,
                    "image_url": ("/web/image/iso.management.evidence/%s/screenshot" % evidence.id) if evidence.capture_status == "captured" else False,
                    "capture_status": evidence.capture_status or False,
                })
                links.append({"source": "c%s" % clause.id, "target": "e%s" % evidence.id, "type": "evidence"})
                links.append({"source": "e%s" % evidence.id, "target": module_nodes[app_key]["id"], "type": "source"})
        nodes.extend(module_nodes.values())
        summary = {"covered": standard.covered_count, "partial": standard.partial_count, "gap": standard.gap_count, "unscanned": standard.unscanned_count}
        return {
            "standard": {"id": standard.id, "name": standard.name},
            "nodes": nodes, "links": links, "summary": summary,
            "rag": {"ready": standard.rag_ready, "info": standard.rag_info},
        }


class IsoManagementClause(models.Model):
    _name = "iso.management.clause"
    _mail_post_access = "read"
    _description = "ISO Management Clause"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "name"
    _order = "catalog_sequence, id"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    standard_id = fields.Many2one("iso.management.standard", string="Standard edition", ondelete="restrict", check_company=True, index=True)
    parent_id = fields.Many2one("iso.management.clause", string="Parent clause", ondelete="restrict", check_company=True)
    catalog_sequence = fields.Integer(default=1000)
    clause_summary = fields.Text(string="Summary")
    practical_guidance = fields.Text(string="Practical guidance", compute="_compute_practical_guidance")
    suggested_evidence = fields.Text(string="Examples to look for", compute="_compute_practical_guidance")

    @api.depends("clause_number", "clause_summary")
    def _compute_practical_guidance(self):
        from .iso_catalog import practical_guidance
        for clause in self:
            clause.practical_guidance, clause.suggested_evidence = practical_guidance(
                clause.clause_number or "", clause.clause_summary or ""
            )
    standard = fields.Char(
        string="Standard",
        required=True,
        default="ISO 14001",
        readonly=True,
        tracking=True,
    )
    edition = fields.Char(string="Edition", required=True, default="2015", tracking=True)
    clause_number = fields.Char(string="Clause", required=True, index=True, tracking=True)
    clause_title = fields.Char(string="Clause title", required=True, tracking=True)
    clause_detail = fields.Text(
        string="Clause detail / organization interpretation",
        help=(
            "Enter the applicable detail or your organization's interpretation "
            "from a licensed copy. ISO text is not preloaded."
        ),
        tracking=True,
    )
    search_keywords = fields.Char(
        string="Detection keywords",
        help="Topics describing this clause. Used as extra context for the RAG provider; the curated rules do not use them.",
    )
    child_ids = fields.One2many("iso.management.clause", "parent_id", string="Sub-clauses")
    coverage_status = fields.Selection(
        [("group", "Heading"), ("covered", "Covered"), ("partial", "Partial"), ("gap", "Gap"), ("unscanned", "Not scanned")],
        compute="_compute_coverage",
    )
    mapped_count = fields.Integer(compute="_compute_coverage", string="Mapped records")
    rag_info = fields.Text(compute="_compute_rag_info", string="RAG & AI")
    all_apps = fields.Boolean(string="Search all installed apps", default=True, tracking=True)
    application_ids = fields.Many2many(
        "ir.module.module",
        "iso_clause_application_rel",
        "clause_id",
        "module_id",
        string="Selected apps",
        domain="[('state', '=', 'installed'), ('application', '=', True)]",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    active = fields.Boolean(default=True, tracking=True)
    scan_ids = fields.One2many("iso.management.scan", "clause_id", string="Detection runs")
    scan_count = fields.Integer(compute="_compute_scan_stats")
    latest_scan_status = fields.Selection(
        selection=[
            ("potential_evidence", "Potential evidence - review required"),
            ("needs_review", "Needs review - no direct evidence found"),
            ("error", "Scan error"),
        ],
        compute="_compute_scan_stats",
    )

    _clause_unique = models.Constraint(
        "unique(standard, edition, clause_number, company_id)",
        "This clause already exists for this standard edition and company.",
    )

    @api.depends("standard", "edition", "clause_number", "clause_title")
    def _compute_name(self):
        for clause in self:
            clause.name = (
                f"{clause.standard or ''}:{clause.edition or ''} "
                f"{clause.clause_number or ''} - {clause.clause_title or ''}"
            ).strip()

    @api.depends("scan_ids", "scan_ids.status", "scan_ids.scan_date")
    def _compute_scan_stats(self):
        for clause in self:
            scans = clause.scan_ids.sorted("scan_date", reverse=True)
            clause.scan_count = len(scans)
            clause.latest_scan_status = scans[:1].status if scans else False

    def _latest_done_scan(self):
        self.ensure_one()
        scans = self.scan_ids.filtered(lambda scan: scan.execution_state == "done" and scan.status != "error")
        return scans.sorted(lambda scan: (scan.scan_date, scan.id), reverse=True)[:1]

    @api.depends("scan_ids.status", "scan_ids.execution_state", "scan_ids.evidence_ids.rule_strength", "child_ids")
    def _compute_coverage(self):
        for clause in self:
            if clause.child_ids:
                clause.coverage_status, clause.mapped_count = "group", 0
                continue
            scan = clause._latest_done_scan()
            if not scan:
                clause.coverage_status, clause.mapped_count = "unscanned", 0
                continue
            matches = scan.evidence_ids.filtered(lambda ev: ev.evidence_type == "rule_match")
            clause.mapped_count = len(matches)
            if not matches:
                clause.coverage_status = "gap"
            elif matches.filtered(lambda ev: ev.rule_strength == "direct"):
                clause.coverage_status = "covered"
            else:
                clause.coverage_status = "partial"

    def _compute_rag_info(self):
        from .iso_providers import config, rag_status
        cfg = config()
        ready, message, _missing = rag_status()
        for clause in self:
            scan = clause._latest_done_scan()
            clause.rag_info = _(
                "Provider used by the last scan: %(last)s\nVector store: pgvector (%(dim)s dimensions, %(embed)s)\nLLM: %(llm)s\nStatus: %(status)s",
                last=(dict(scan._fields["provider"].selection).get(scan.provider) if scan else _("none yet")),
                dim=cfg["embed_dim"], embed="%s / %s" % (cfg["embed_provider"], cfg["embed_model"]),
                llm=cfg["ai_model"], status=message)

    @api.constrains("all_apps", "application_ids")
    def _check_app_scope(self):
        for clause in self:
            if not clause.all_apps and not clause.application_ids:
                raise UserError(_("Select at least one installed app, or enable Search all installed apps."))

    def action_run_detection(self):
        self.ensure_one()
        return self._queue_scan(self.env["iso.management.scan"]._default_provider())

    def action_run_rag_detection(self):
        self.ensure_one()
        from .iso_providers import rag_status
        ready, message, _missing = rag_status()
        if not ready:
            raise UserError(message)
        return self._queue_scan("rag")

    def _queue_scan(self, provider):
        scan = self.env["iso.management.scan"].create(
            {
                "clause_id": self.id,
                "company_id": self.company_id.id,
                "scan_date": fields.Datetime.now(),
                "status": "needs_review",
                "detector_version": "3",
                "provider": provider,
                "execution_state": "queued",
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Detection run"),
            "res_model": "iso.management.scan",
            "res_id": scan.id,
            "view_mode": "form",
            "target": "current",
        }


class IsoManagementScan(models.Model):
    _name = "iso.management.scan"
    _description = "ISO Evidence Detection Run"
    _inherit = ["mail.thread"]
    _order = "scan_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    clause_id = fields.Many2one(
        "iso.management.clause", required=True, ondelete="cascade", index=True, tracking=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    scan_date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    completed_date = fields.Datetime(readonly=True)
    status = fields.Selection(
        [
            ("potential_evidence", "Potential evidence - review required"),
            ("needs_review", "Needs review - no direct evidence found"),
            ("error", "Scan error"),
        ],
        required=True,
        default="needs_review",
        tracking=True,
        index=True,
    )
    detector_version = fields.Char(readonly=True)
    provider = fields.Selection([("rules", "Curated rules"), ("rag", "RAG + AI")], required=True, default=lambda self: "rag" if self._default_provider() == "rag" else "rules", readonly=True)
    execution_state = fields.Selection([("queued", "Queued"), ("running", "Scanning"), ("done", "Search complete"), ("error", "Scan failed")], readonly=True, index=True)
    execution_started = fields.Datetime(readonly=True)
    execution_token = fields.Char(readonly=True)
    progress_state = fields.Char(compute="_compute_progress_state", string="Progress")
    summary = fields.Text(readonly=True)
    explanation = fields.Text(readonly=True)
    scope_summary = fields.Text(readonly=True)
    app_count = fields.Integer(readonly=True)
    model_count = fields.Integer(readonly=True)
    matched_record_count = fields.Integer(readonly=True)
    evidence_ids = fields.One2many("iso.management.evidence", "scan_id", string="Evidence")
    candidate_ids = fields.One2many("iso.management.evidence", "scan_id", domain=[("evidence_type", "in", ["rule_match", "keyword_match"])], string="Mapped evidence")
    context_ids = fields.One2many("iso.management.evidence", "scan_id", domain=[("evidence_type", "not in", ["rule_match", "keyword_match"])], string="Other scan context")
    context_screenshot_ids = fields.One2many("iso.management.evidence", "scan_id", domain=[("evidence_type", "=", "operational_context"), ("source_record_id", ">", 0)], string="Example app screenshots")
    capture_counts = fields.Char(compute="_compute_capture_counts", string="Screenshots")

    screenshot = fields.Image(
        string="Screenshot",
        attachment=True,
        max_width=1920,
        max_height=1920,
        help="Upload a screenshot that supports this review. It supplements, not replaces, record evidence.",
    )
    screenshot_filename = fields.Char(string="Screenshot filename")

    @api.depends("evidence_ids.capture_status", "evidence_ids.evidence_type")
    def _compute_capture_counts(self):
        for scan in self:
            matches = scan.evidence_ids.filtered(lambda ev: ev.evidence_type in ("rule_match", "keyword_match", "operational_context") and ev.capture_status)
            scan.capture_counts = _("%(captured)s captured, %(waiting)s waiting, %(failed)s failed",
                captured=len(matches.filtered(lambda ev: ev.capture_status == "captured")),
                waiting=len(matches.filtered(lambda ev: ev.capture_status in ("pending", "capturing"))),
                failed=len(matches.filtered(lambda ev: ev.capture_status == "failed")))

    @api.depends("execution_state", "status", "evidence_ids.capture_status", "evidence_ids.evidence_type")
    def _compute_progress_state(self):
        for scan in self:
            scan.progress_state = scan._progress_data()["label"]

    def _progress_data(self):
        self.ensure_one()
        matches = self.evidence_ids.filtered(lambda e: e.evidence_type in ("rule_match", "keyword_match", "operational_context") and e.capture_status)
        waiting = len(matches.filtered(lambda e: e.capture_status in ("pending", "capturing")))
        failed = len(matches.filtered(lambda e: e.capture_status == "failed"))
        captured = len(matches.filtered(lambda e: e.capture_status == "captured"))
        if self.execution_state == "queued":
            state, label = "queued", _("Queued")
        elif self.execution_state == "running":
            state, label = "running", _("Scanning")
        elif self.execution_state == "error" or self.status == "error":
            state, label = "error", _("Scan failed")
        elif waiting:
            state, label = "capturing", _("Capturing screenshots")
        elif failed:
            state, label = "partial", _("Done with screenshot failures")
        elif not captured and not self.matched_record_count:
            state, label = "empty", _("Done - no app screenshot available")
        else:
            state, label = "done", _("Done")
        return {"state": state, "label": label, "captured": captured, "waiting": waiting, "failed": failed}

    @api.model
    def get_progress(self, scan_id=False):
        if scan_id:
            scan = self.browse(int(scan_id)).exists()
            if not scan:
                return False
            scan.check_access("read")
            return scan._progress_data()
        scans = self.search([("company_id", "in", self.env.companies.ids), "|", ("execution_state", "in", ["queued", "running"]), ("evidence_ids.capture_status", "in", ["pending", "capturing"])])
        return {"running": sum(scan._progress_data()["state"] in ("queued", "running", "capturing") for scan in scans)}

    @api.model
    def claim_scan(self):
        if not self.env.user.has_group("iso_management.group_iso_capture_worker"):
            raise AccessError(_("Only the capture worker can claim scan jobs."))
        stale = fields.Datetime.now() - timedelta(minutes=20)
        self.env.cr.execute("""SELECT id FROM iso_management_scan
            WHERE company_id = ANY(%s) AND (execution_state = 'queued'
                OR (execution_state = 'running' AND execution_started < %s))
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1""", (self.env.user.company_ids.ids, stale))
        row = self.env.cr.fetchone()
        if not row:
            return False
        scan = self.sudo().browse(row[0])
        token = uuid.uuid4().hex
        scan.write({"execution_state": "running", "execution_started": fields.Datetime.now(), "execution_token": token})
        return {"id": scan.id, "token": token}

    @api.model
    def execute_scan(self, scan_id, token):
        if not self.env.user.has_group("iso_management.group_iso_capture_worker"):
            raise AccessError(_("Only the capture worker can run scan jobs."))
        self.env.cr.execute("SELECT id FROM iso_management_scan WHERE id = %s FOR UPDATE", (int(scan_id),))
        scan = self.sudo().browse(int(scan_id)).exists()
        if not scan or scan.execution_state != "running" or scan.execution_token != token:
            raise AccessError(_("Scan job is no longer assigned to this worker."))
        requester = scan.create_uid
        try:
            if not requester.active or scan.company_id not in requester.company_ids or scan.company_id not in self.env.user.company_ids:
                raise AccessError(_("The scanner or capture worker no longer has access to this company."))
            original = scan.with_user(requester).with_context(allowed_company_ids=[scan.company_id.id]).with_company(scan.company_id)
            original.check_access("read")
            original._run_detection()
            scan.write({"execution_state": "error" if scan.status == "error" else "done", "execution_token": False})
        except Exception as error:
            _logger.exception("Background ISO scan %s failed", scan.id)
            scan.write({"execution_state": "error", "status": "error", "completed_date": fields.Datetime.now(), "summary": _("The scan could not complete."), "explanation": str(error)[:1000], "execution_token": False})
        return True

    @api.model
    def _default_provider(self):
        from .iso_providers import config, rag_status
        return "rag" if config()["provider"] == "rag" and rag_status()[0] else "rules"

    @api.depends("clause_id.name", "scan_date")
    def _compute_name(self):
        for scan in self:
            if scan.clause_id and scan.scan_date:
                scan.name = _("%(clause)s - %(date)s", clause=scan.clause_id.name, date=fields.Datetime.to_string(scan.scan_date))
            else:
                scan.name = scan.clause_id.name or _("New detection run")

    def _scope_modules(self):
        Module = self.env["ir.module.module"]
        installed = Module.search([("state", "=", "installed")])
        by_name = {module.name: module for module in installed}
        clause = self.clause_id
        roots = (clause.application_ids if not clause.all_apps else installed.filtered("application")).filtered(lambda module: module.name != "iso_management")
        module_names = set()
        for root in roots:
            pending = [root]
            while pending:
                module = pending.pop()
                if module.name in module_names:
                    continue
                module_names.add(module.name)
                for dependency_name in module.dependencies_id.mapped("name"):
                    dependency = by_name.get(dependency_name)
                    if dependency and dependency_name not in module_names:
                        pending.append(dependency)
        app_names = sorted(
            {
                (module.shortdesc or module.name)
                for module in roots
            },
            key=str.casefold,
        )
        return installed, module_names, app_names

    def _eligible_capture_models(self):
        self.ensure_one()
        installed, modules, _app_names = self._scope_modules()
        root_ids = self.env["ir.ui.menu"].get_user_roots().ids
        visible_modules = set(self.env["ir.model.data"].sudo().search([
            ("model", "=", "ir.ui.menu"), ("res_id", "in", root_ids)
        ]).mapped("module")) - {"base", "iso_management"}
        by_name = {module.name: module for module in installed}
        app_modules = set()
        for app in installed.filtered(lambda module: module.application and module.name != "iso_management"):
            closure, pending = set(), [app]
            while pending:
                module = pending.pop()
                if module.name in closure:
                    continue
                closure.add(module.name)
                pending.extend(by_name[name] for name in module.dependencies_id.mapped("name") if name in by_name and name not in closure)
            if closure & visible_modules:
                app_modules.update(closure)
        model_map = self._module_model_map(modules & app_modules)
        return set().union(*model_map.values()) if model_map else set()

    def _module_model_map(self, module_names):
        model_data = self.env["ir.model.data"].sudo().search(
            [("model", "=", "ir.model"), ("module", "in", list(module_names))]
        )
        model_ids_by_module = defaultdict(set)
        for data in model_data:
            model_ids_by_module[data.module].add(data.res_id)
        module_models = {}
        for module_name, model_ids in model_ids_by_module.items():
            module_models[module_name] = set(
                self.env["ir.model"].sudo().browse(list(model_ids)).exists().mapped("model")
            )
        return module_models

    @staticmethod
    def _safe_text_fields(model):
        fields_by_name = model._fields
        visible_fields = set(model.fields_get(attributes=["type"]))
        candidates = []
        for field_name, field in fields_by_name.items():
            if field_name not in visible_fields:
                continue
            if field.type not in {"char", "text", "html"} or not field.store:
                continue
            if any(part in field_name.lower() for part in SENSITIVE_FIELD_PARTS):
                continue
            candidates.append(field_name)

        ordered = [name for name in PREFERRED_TEXT_FIELDS if name in candidates]
        semantic = []
        for field_name in candidates:
            field = fields_by_name[field_name]
            label = str(field.string or "").lower()
            if any(term in field_name.lower() or term in label for term in ENVIRONMENTAL_FIELD_TERMS):
                semantic.append(field_name)
        return list(dict.fromkeys(semantic + ordered + candidates))[:5]

    @staticmethod
    def _plain_excerpt(value, limit=600):
        text = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
        return re.sub(r"\s+", " ", text).strip()[:limit]

    def _create_context_evidence(self, capture_examples=False):
        Evidence = self.env["iso.management.evidence"]
        rows = []
        total_context = 0
        for model_name, label in CONTEXT_MODELS:
            if model_name not in self.env.registry.models:
                continue
            model = self.env[model_name]
            try:
                if not model.has_access("read"):
                    continue
                count = model.search_count([])
            except (AccessError, UserError):
                continue
            total_context += count
            if count:
                rows.append(
                    {
                        "scan_id": self.id,
                        "name": label,
                        "evidence_type": "operational_context",
                        "source_app": self._app_for_model(model_name),
                        "source_model": model_name,
                        "record_count": count,
                        "excerpt": _(
                            "%(count)s records were visible to the scanner. This is operational context only, "
                            "not proof of environmental assessment or conformity.",
                            count=count,
                        ),
                    }
                )
        if rows:
            context_rows = Evidence.create(rows)
            if capture_examples:
                context_rows._queue_context_capture()
        return total_context

    def _app_for_model(self, model_name):
        xmlid = "model_" + model_name.replace(".", "_")
        data = self.env["ir.model.data"].sudo().search(
            [("model", "=", "ir.model"), ("name", "=", xmlid)], limit=1)
        if data:
            module = self.env["ir.module.module"].sudo().search([("name", "=", data.module)], limit=1)
            if module:
                return module.shortdesc or module.name
        return _("Installed Odoo app")


    def _run_detection(self):
        from .iso_providers import get_provider
        for scan in self:
            scan = scan.with_context(allowed_company_ids=[scan.company_id.id])
            if scan.evidence_ids:
                raise UserError(_("This scan already has results. Run a new scan from the clause."))
            try:
                provider = get_provider(scan.provider)
                result = provider.detect(scan)
                rows, gaps = result["rows"], result["gaps"]
                rows.sort(key=lambda row: -row["relevance_score"])
                for index, row in enumerate(rows):
                    if index < 4:  # screenshot only the strongest evidence per clause
                        row["capture_status"] = "pending"
                Evidence = scan.env["iso.management.evidence"]
                if rows:
                    Evidence.create(rows)
                for text in gaps:
                    Evidence.create({
                        "scan_id": scan.id, "name": _("Evidence gap"), "evidence_type": "gap",
                        "provider": scan.provider, "source_app": _("Installed Odoo apps"), "record_count": 0,
                        "excerpt": text,
                    })
                direct = sum(1 for row in rows if row.get("rule_strength") == "direct")
                if rows:
                    summary = _("%(n)s record(s) mapped to this clause (%(d)s direct). Review each one; this is not a conformity decision.", n=len(rows), d=direct)
                else:
                    summary = _("No Odoo record is mapped to this clause yet - an evidence gap to close manually.")
                scan.write({
                    "status": "potential_evidence" if rows else "needs_review",
                    "completed_date": fields.Datetime.now(),
                    "summary": summary,
                    "explanation": _("Provider: %(provider)s. Mapping rules for clause %(number)s were evaluated against live Odoo data.", provider=scan.provider, number=scan.clause_id.clause_number),
                    "scope_summary": _("Records are read with the scanning user's access rights. Private HR, authentication, biometric and user/partner data are excluded."),
                    "app_count": len({row["source_app"] for row in rows}),
                    "model_count": result.get("models", 0),
                    "matched_record_count": len(rows),
                    "detector_version": "3",
                })
            except Exception as error:
                _logger.exception("ISO Management detection failed for scan %s", scan.id)
                scan.write({
                    "status": "error", "completed_date": fields.Datetime.now(),
                    "summary": _("The scan could not complete."), "explanation": str(error)[:1000],
                })


    def action_print_report(self):
        self.ensure_one()
        return self.env.ref("iso_management.action_report_iso_scan").report_action(self)


class IsoManagementEvidence(models.Model):
    _name = "iso.management.evidence"
    _description = "ISO Management Evidence"
    _order = "relevance_score desc, evidence_type, source_app, source_model, id"
    _check_company_auto = True

    scan_id = fields.Many2one("iso.management.scan", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="scan_id.company_id", store=True, index=True)
    name = fields.Char(required=True)
    evidence_type = fields.Selection(
        [
            ("rule_match", "Mapped record"),
            ("keyword_match", "Potential record match (legacy)"),
            ("operational_context", "Operational context only"),
            ("metadata", "Model metadata"),
            ("gap", "Evidence gap"),
        ],
        required=True,
        default="rule_match",
    )
    provider = fields.Selection([("rules", "Curated rules"), ("rag", "RAG + AI")], readonly=True, default="rules")
    rule_strength = fields.Selection([("direct", "Direct"), ("supporting", "Supporting")], readonly=True)
    source_app = fields.Char()
    source_model = fields.Char()
    source_record_id = fields.Integer()
    source_record_name = fields.Char()
    source_field = fields.Char()
    match_term = fields.Char()
    matched_terms = fields.Char(string="Matched terms", readonly=True)
    relevance_score = fields.Integer(string="Rule-based relevance score", readonly=True)
    match_reason = fields.Text(string="Why selected", readonly=True)
    screenshot = fields.Binary(string="Source screenshot", attachment=True, readonly=True)
    screenshot_is_original = fields.Boolean(string="Unaltered screenshot", readonly=True, default=False)
    capture_status = fields.Selection([("pending", "Pending"), ("capturing", "Capturing"), ("captured", "Captured"), ("failed", "Failed")], readonly=True, index=True)
    capture_error = fields.Char(string="Capture status detail", readonly=True)
    capture_owner_id = fields.Many2one("res.users", readonly=True)
    capture_started = fields.Datetime(readonly=True)
    captured_at = fields.Datetime(readonly=True)
    source_page_model = fields.Char(string="Captured page model", readonly=True)
    source_page_record_id = fields.Integer(string="Captured page record", readonly=True)
    source_page_name = fields.Char(string="Captured page", readonly=True)
    record_count = fields.Integer()
    excerpt = fields.Text()
    source_url = fields.Char(compute="_compute_source_url")
    source_page_url = fields.Char(compute="_compute_source_url")

    def _queue_context_capture(self):
        """Queue representative app records as context, never as clause matches."""
        eligible_cache = {}
        allowed_models = {model for model, _label in CONTEXT_MODELS}
        for evidence in self.sudo():
            if evidence.evidence_type != "operational_context" or evidence.capture_status or evidence.source_record_id or evidence.source_model not in allowed_models:
                continue
            requester = evidence.create_uid
            company = evidence.company_id
            if not requester.active or company not in requester.company_ids:
                continue
            context = {"allowed_company_ids": [company.id]}
            key = (evidence.scan_id.id, requester.id)
            if key not in eligible_cache:
                eligible_cache[key] = evidence.scan_id.with_user(requester).with_context(**context).with_company(company)._eligible_capture_models()
            if evidence.source_model not in eligible_cache[key]:
                continue
            model = self.env[evidence.source_model].with_user(requester).with_context(**context).with_company(company)
            try:
                with self.env.cr.savepoint():
                    if not model.has_access("read"):
                        continue
                    domain = []
                    if "company_id" in model._fields:
                        domain = ["|", ("company_id", "=", False), ("company_id", "=", company.id)]
                    record = model.search(domain, limit=1, order="id")
                    if not record:
                        continue
                    record.check_access("read")
                    record_name = record.display_name
                evidence.write({
                    "source_record_id": record.id,
                    "source_record_name": record_name,
                    "capture_status": "pending",
                    "capture_error": False,
                    "match_reason": _("A representative record from %(app)s, shown as app context. It was not selected by a clause keyword match and does not establish conformity.", app=evidence.source_app or _("an installed app")),
                })
            except (AccessError, UserError, ValueError, psycopg2.Error):
                _logger.info("Unable to select an accessible context record for evidence %s", evidence.id)
        return True

    def action_retry_capture(self):
        self.check_access("read")
        for evidence in self:
            if evidence.evidence_type in ("rule_match", "keyword_match", "operational_context") and evidence.source_record_id and evidence.capture_status in ("failed", "captured"):
                evidence.sudo().write({"capture_status": "pending", "capture_error": False, "capture_owner_id": False, "capture_started": False})
        return True

    def _capture_target(self, source):
        """Return the Odoo page that best represents this source record."""
        self.ensure_one()
        if source._name == "sale.order.template.line" and source.sale_order_template_id:
            return source.sale_order_template_id
        if source._name == "stock.move" and source.product_tmpl_id:
            # Odoo's move form loads extra inventory operations that this
            # read-only worker cannot inspect. Use the linked product page as
            # safe in-app context while retaining the move as the source link.
            return source.product_tmpl_id
        if source._name == "ir.attachment":
            owner_model = source.res_model
            owner_id = source.res_id
            if (
                owner_model
                and owner_id
                and owner_model in self.env.registry.models
                and owner_model not in SENSITIVE_MODELS
                and not owner_model.startswith(SENSITIVE_MODEL_PREFIXES)
            ):
                return self.env[owner_model].browse(owner_id).exists()
            return self.env["ir.attachment"]
        return source

    @api.model
    def capture_next(self):
        if not self.env.user.has_group("iso_management.group_iso_capture_worker"):
            raise AccessError(_("Only the capture worker can claim screenshot jobs."))
        Evidence = self.sudo()
        stale = fields.Datetime.now() - timedelta(minutes=5)
        stale_jobs = Evidence.search([("capture_status", "=", "capturing"), ("capture_started", "<", stale)])
        for job in stale_jobs:
            job._revoke_capture_access()
        stale_jobs.write({"capture_status": "pending", "capture_owner_id": False, "capture_started": False})
        base_domain = [("capture_status", "=", "pending"), ("company_id", "in", self.env.user.company_ids.ids)]
        candidates = Evidence.search(base_domain + [("evidence_type", "in", ["rule_match", "keyword_match"])], limit=30, order="id desc")
        if not candidates:
            candidates = Evidence.search(base_domain + [("evidence_type", "=", "operational_context")], limit=30, order="id desc")
        for evidence in candidates:
            model_name, field_name = evidence.source_model, evidence.source_field
            try:
                if not model_name or model_name in SENSITIVE_MODELS or (model_name.startswith(SENSITIVE_MODEL_PREFIXES) and model_name != "ir.attachment") or model_name not in self.env.registry.models:
                    raise AccessError(_("Source model is excluded."))
                context = {"allowed_company_ids": [evidence.company_id.id]}
                source_model = self.env[model_name].with_context(**context).with_company(evidence.company_id)
                if evidence.evidence_type == "keyword_match" and field_name not in self.env["iso.management.scan"]._safe_text_fields(source_model):
                    raise AccessError(_("Source field is excluded."))
                if evidence.evidence_type == "operational_context" and model_name not in {model for model, _label in CONTEXT_MODELS}:
                    raise AccessError(_("This model cannot be used for app context."))
                requester = evidence.create_uid
                if evidence.company_id not in requester.company_ids:
                    raise AccessError(_("The original scanner no longer has access to this company."))
                original = self.env[model_name].with_user(requester).with_context(**context).with_company(evidence.company_id).browse(evidence.source_record_id).exists()
                if not original:
                    raise AccessError(_("Source record no longer exists."))
                original.check_access("read")
                eligible_models = evidence.scan_id.with_user(requester).with_context(**context).with_company(evidence.company_id)._eligible_capture_models()
                if model_name != "ir.attachment" and (model_name not in eligible_models or model_name.startswith("onboarding.")):
                    raise AccessError(_("This source does not belong to an eligible installed app."))
                if evidence.evidence_type == "keyword_match":
                    source_value = original.read([field_name])[0].get(field_name)
                    if not evidence.match_term or evidence.match_term.lower() not in self.env["iso.management.scan"]._plain_excerpt(source_value).lower():
                        raise UserError(_("The matched field changed since the scan; run a new scan."))
                target = evidence._capture_target(original)
                if not target:
                    if model_name == "ir.attachment":
                        raise AccessError(_("The attachment is not linked to an eligible installed app record."))
                    raise AccessError(_("The linked source page no longer exists."))
                target_model_name = target._name
                if target_model_name not in eligible_models or target_model_name.startswith(("iso.management.", "onboarding.")) or target_model_name in SENSITIVE_MODELS or target_model_name.startswith(SENSITIVE_MODEL_PREFIXES):
                    raise AccessError(_("The linked page does not belong to an eligible installed app."))
                target_original = self.env[target_model_name].with_user(requester).with_context(**context).with_company(evidence.company_id).browse(target.id).exists()
                if not target_original:
                    raise AccessError(_("The original scanner cannot open the linked source page."))
                target_original.check_access("read")
                if "company_id" in target_original._fields and target_original.company_id and target_original.company_id != evidence.company_id:
                    raise AccessError(_("The linked source page belongs to another company."))
                allowed_fields = sorted(set(original.fields_get()) | set(target_original.fields_get()))

                # Give the capture worker record-scoped read access only for this job.
                group = self.env.ref("iso_management.group_iso_capture_worker")
                access_model = self.env["ir.access"].sudo()
                evidence._revoke_capture_access()
                grant_records = {}
                for grant_model, record_id in ((model_name, original.id), (target_model_name, target_original.id)):
                    grant_records.setdefault(grant_model, set()).add(record_id)
                # Order forms render their lines; grant those lines read access for this job only.
                for page_record in (original, target_original):
                    line_field = page_record._fields.get("order_line")
                    if line_field is not None and line_field.type == "one2many" and page_record.order_line:
                        lines = page_record.order_line
                        lines.check_access("read")
                        grant_records.setdefault(lines._name, set()).update(lines.ids)
                        # "product_and_description" is a view widget over product_id + name, both readable here.
                        allowed_fields = sorted(set(allowed_fields) | set(lines.fields_get()) | {"product_and_description"})
                for grant_model, record_ids in grant_records.items():
                    metadata = self.env["ir.model"].sudo().search([("model", "=", grant_model)], limit=1)
                    if not metadata:
                        raise AccessError(_("The source page model is unavailable."))
                    access_model.create({
                        "name": "ISO capture job %s: %s" % (evidence.id, grant_model),
                        "model_id": metadata.id,
                        "group_id": group.id,
                        "operation": "r",
                        "domain": repr([("id", "in", sorted(record_ids))]),
                    })
                source = source_model.browse(original.id).exists()
                target_worker = self.env[target_model_name].with_context(**context).with_company(evidence.company_id).browse(target_original.id).exists()
                if not source or not target_worker:
                    raise AccessError(_("The capture account cannot open the source record."))
                target_model = self.env[target_model_name].with_context(**context).with_company(evidence.company_id)
                if not source_model.has_access("read") or not target_model.has_access("read"):
                    raise AccessError(_("The capture account cannot read the source page."))
                source.check_access("read")
                target_worker.check_access("read")
            except (AccessError, UserError, ValueError, KeyError) as error:
                evidence._revoke_capture_access()
                detail = str(error)[:170]
                if evidence.screenshot:
                    detail += _(" Previous screenshot remains available.")
                evidence.write({"capture_status": "failed", "capture_error": detail[:240], "capture_owner_id": False, "capture_started": False})
                continue
            evidence.write({
                "capture_status": "capturing",
                "capture_owner_id": self.env.uid,
                "capture_started": fields.Datetime.now(),
                "capture_error": False,
                "source_page_model": target_model_name,
                "source_page_record_id": target_original.id,
                "source_page_name": target_original.display_name or target_model_name,
            })
            return {
                "id": evidence.id,
                "model": target_model_name,
                "record_id": target_original.id,
                "field": field_name or "name",
                "source_model": model_name,
                "source_record_id": evidence.source_record_id,
                "source_record_name": evidence.source_record_name or "",
                "match_term": evidence.match_term or "",
                "excerpt": evidence.excerpt or "",
                "allowed_fields": allowed_fields,
                "company_id": evidence.company_id.id,
            }
        return False

    def _revoke_capture_access(self):
        for evidence in self:
            if not evidence.source_model:
                continue
            access_model = self.env["ir.access"].sudo()
            worker_group = self.env.ref("iso_management.group_iso_capture_worker")
            job_prefix = "ISO capture job %s: " % evidence.id
            access_model.search([("name", "like", job_prefix + "%"), ("group_id", "=", worker_group.id)]).unlink()
            # Revoke any restricted grant left by versions before job-scoped access was added.
            legacy = access_model.search([("name", "=", "ISO capture: " + evidence.source_model), ("group_id", "=", worker_group.id)])
            if legacy:
                legacy.write({"domain": "[('id', '=', 0)]"})

    @api.model
    def capture_finish(self, evidence_id, image_data=False, error=False, unaltered=False):
        if not self.env.user.has_group("iso_management.group_iso_capture_worker"):
            raise AccessError(_("Only the capture worker can complete screenshot jobs."))
        evidence = self.sudo().browse(int(evidence_id)).exists()
        if not evidence or evidence.capture_status != "capturing" or evidence.capture_owner_id.id != self.env.uid:
            raise AccessError(_("Screenshot job is not assigned to this worker."))
        evidence._revoke_capture_access()
        if error:
            detail = str(error)[:170]
            if evidence.screenshot:
                detail += _(" Previous screenshot remains available.")
            evidence.write({"capture_status": "failed", "capture_error": detail[:240], "capture_owner_id": False, "capture_started": False})
            return True
        try:
            raw = base64.b64decode(image_data or "", validate=True)
        except (ValueError, binascii.Error):
            raise UserError(_("Invalid screenshot data."))
        valid_png = raw.startswith(b"\x89PNG\r\n\x1a\n")
        valid_jpeg = raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")
        if len(raw) > 10 * 1024 * 1024 or not (valid_png or valid_jpeg):
            detail = _("The full-page screenshot could not be saved. Retry the capture.")
            if evidence.screenshot:
                detail += _(" Previous screenshot remains available.")
            evidence.write({"capture_status": "failed", "capture_error": detail[:240], "capture_owner_id": False, "capture_started": False})
            return True
        evidence.write({"screenshot": image_data, "screenshot_is_original": bool(unaltered), "capture_status": "captured", "captured_at": fields.Datetime.now(), "capture_owner_id": False, "capture_started": False, "capture_error": False})
        return True

    @api.depends("source_model", "source_record_id", "source_page_model", "source_page_record_id", "company_id")
    def _compute_source_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_str("web.base.url", "")
        for evidence in self:
            company_suffix = "?cids=%s" % evidence.company_id.id if evidence.company_id else ""
            if evidence.source_model and evidence.source_record_id:
                evidence.source_url = f"{base_url}/odoo/{evidence.source_model}/{evidence.source_record_id}{company_suffix}"
            else:
                evidence.source_url = False
            page_model = evidence.source_page_model or evidence.source_model
            page_id = evidence.source_page_record_id or evidence.source_record_id
            evidence.source_page_url = f"{base_url}/odoo/{page_model}/{page_id}{company_suffix}" if page_model and page_id else False
