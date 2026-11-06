"""pgvector-backed chunk index used by the RAG provider."""

import hashlib
import logging

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from . import iso_providers
from .iso_rules import RULES

_logger = logging.getLogger(__name__)

# Record types indexed for retrieval: every model the curated rules know about
# plus core transactional documents. Only titles / short safe text are embedded.
EXTRA_MODELS = ("sale.order", "purchase.order", "stock.picking", "crm.lead")
MAX_RECORDS_PER_MODEL = 500


class IsoManagementChunk(models.Model):
    _name = "iso.management.chunk"
    _description = "ISO RAG Index Chunk"
    _log_access = False

    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    model = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True)
    text = fields.Text()
    content_hash = fields.Char()
    indexed_at = fields.Datetime(default=fields.Datetime.now)
    # The `vector` column is created in init() (pgvector); it is not an ORM field.

    _unique_record = models.Constraint(
        "unique(company_id, model, res_id)", "A record is indexed only once per company."
    )

    def init(self):
        dim = iso_providers.config()["embed_dim"]
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.env.cr.execute(
                    "ALTER TABLE iso_management_chunk ADD COLUMN IF NOT EXISTS embedding vector(%s)" % int(dim))
        except psycopg2.Error:
            _logger.warning("pgvector is unavailable; the ISO RAG provider cannot index until it is installed.")

    @api.model
    def index_count(self, company_id=False):
        domain = [("company_id", "=", company_id)] if company_id else []
        return self.sudo().search_count(domain)

    @api.model
    def search_similar(self, vector, company_id, top_k):
        literal = "[" + ",".join("%.8f" % value for value in vector) + "]"
        self.env.cr.execute(
            """SELECT model, res_id, text, embedding <=> %s::vector AS distance
                 FROM iso_management_chunk
                WHERE company_id = %s AND embedding IS NOT NULL
             ORDER BY distance LIMIT %s""",
            (literal, company_id, int(top_k)),
        )
        return self.env.cr.fetchall()

    @api.model
    def _index_models(self):
        names = {rule["model"] for rules in RULES.values() for rule in rules}
        names.update(EXTRA_MODELS)
        return sorted(name for name in names if name in self.env.registry.models and not iso_providers._is_sensitive(name))

    @api.model
    def reindex(self, company):
        ready, message, _missing = iso_providers.rag_status()
        if not ready:
            raise UserError(message)
        Scan = self.env["iso.management.scan"]
        pending = []
        existing = {(c.model, c.res_id): c.content_hash for c in self.sudo().search([("company_id", "=", company.id)])}
        for model_name in self._index_models():
            model = self.env[model_name].with_company(company).with_context(allowed_company_ids=[company.id])
            try:
                if not model.has_access("read"):
                    continue
                with self.env.cr.savepoint():
                    records = model.search([], limit=MAX_RECORDS_PER_MODEL, order="id desc")
                    text_fields = Scan._safe_text_fields(model) if model_name != "ir.attachment" else ["name"]
                    for record in records:
                        parts = [record.display_name or ""]
                        for field_name in text_fields[:3]:
                            value = Scan._plain_excerpt(record[field_name], 300)
                            if value and value not in parts:
                                parts.append(value)
                        text = (" | ".join(part for part in parts if part))[:800]
                        if model_name == "ir.attachment" and record.res_model:
                            text += " (attached to %s)" % record.res_model
                        digest = hashlib.sha1(text.encode()).hexdigest()
                        if existing.get((model_name, record.id)) != digest and text:
                            pending.append((model_name, record.id, text, digest))
            except (AccessError, UserError, ValueError, psycopg2.Error):
                continue
        for start in range(0, len(pending), 64):
            batch = pending[start:start + 64]
            vectors = iso_providers.embed([item[2] for item in batch])
            for (model_name, res_id, text, digest), vector in zip(batch, vectors):
                literal = "[" + ",".join("%.8f" % value for value in vector) + "]"
                self.env.cr.execute(
                    """INSERT INTO iso_management_chunk (company_id, model, res_id, text, content_hash, embedding, indexed_at)
                       VALUES (%s, %s, %s, %s, %s, %s::vector, now() at time zone 'utc')
                       ON CONFLICT (company_id, model, res_id)
                       DO UPDATE SET text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                                     embedding = EXCLUDED.embedding, indexed_at = EXCLUDED.indexed_at""",
                    (company.id, model_name, res_id, text, digest, literal),
                )
        return len(pending)
