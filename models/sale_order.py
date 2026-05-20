import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleOrderPlugitRate(models.Model):
    _inherit = 'sale.order'

    # ── Root pricelist (traversed chain) ─────────────────────────────
    plugit_base_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Базовий прайс-лист',
        compute='_compute_plugit_base_pricelist',
        store=True,
        readonly=True,
        help='Кореневий прайс-лист після обходу ланцюжка',
    )
    plugit_pricelist_currency_id = fields.Many2one(
        'res.currency',
        string='Валюта базового прайс-листа',
        related='plugit_base_pricelist_id.currency_id',
        store=True,
        readonly=True,
    )

    # ── Exchange rate ─────────────────────────────────────────────────
    plugit_rate = fields.Float(
        string='Курс',
        digits=(16, 6),
        compute='_compute_plugit_rate',
        store=True,
        readonly=False,
        help='Скільки одиниць валюти замовлення за 1 одиницю базового прайс-листа',
    )
    plugit_rate_label = fields.Char(
        string='Курс',
        compute='_compute_plugit_rate_label',
        help='Відображення курсу у вигляді "41.50 UAH за 1 EUR"',
    )

    # ── Pricelist chain traversal ─────────────────────────────────────

    @api.depends('pricelist_id', 'pricelist_id.item_ids.base',
                 'pricelist_id.item_ids.base_pricelist_id')
    def _compute_plugit_base_pricelist(self):
        for order in self:
            order.plugit_base_pricelist_id = self._get_root_pricelist(order.pricelist_id)

    @api.model
    def _get_root_pricelist(self, pricelist):
        """Walk the pricelist chain and return the deepest base pricelist.

        Traverses ``base_pricelist_id`` references on pricelist items with
        ``compute_price == 'pricelist'``.  Stops at the first pricelist that
        has no such items, or when a cycle is detected.
        """
        if not pricelist:
            return False
        visited = set()
        current = pricelist
        while current and current.id not in visited:
            visited.add(current.id)
            base_items = current.item_ids.filtered(
                lambda i: i.base == 'pricelist' and i.base_pricelist_id
            )
            if base_items:
                candidate = base_items[0].base_pricelist_id
                if candidate and candidate.id not in visited:
                    current = candidate
                    continue
            break
        return current

    # ── Rate computation ──────────────────────────────────────────────

    @api.depends(
        'plugit_pricelist_currency_id',
        'plugit_pricelist_currency_id.rate_ids.rate',
        'currency_id',
        'currency_id.rate_ids.rate',
        'date_order',
    )
    def _compute_plugit_rate(self):
        for order in self:
            pl_cur = order.plugit_pricelist_currency_id
            ord_cur = order.currency_id
            if not pl_cur or not ord_cur or pl_cur == ord_cur:
                order.plugit_rate = 1.0
                continue
            date = (
                order.date_order.date()
                if order.date_order
                else fields.Date.today()
            )
            try:
                rate = pl_cur._get_conversion_rate(
                    pl_cur, ord_cur, order.company_id, date,
                )
            except Exception:
                _logger.warning('Не вдалося отримати курс для замовлення %s', order.name)
                rate = 1.0
            order.plugit_rate = rate

    @api.depends('plugit_rate', 'plugit_pricelist_currency_id', 'currency_id')
    def _compute_plugit_rate_label(self):
        for order in self:
            pl_cur = order.plugit_pricelist_currency_id
            ord_cur = order.currency_id
            if not pl_cur or not ord_cur or pl_cur == ord_cur or not order.plugit_rate:
                order.plugit_rate_label = ''
                continue
            order.plugit_rate_label = '%.6f %s за 1 %s' % (
                order.plugit_rate,
                ord_cur.name,
                pl_cur.name,
            )

    # ── Copy rate to new invoice ──────────────────────────────────────

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['plugit_rate'] = self.plugit_rate
        return vals
