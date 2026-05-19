import logging

from odoo import Command, _, api, fields, models

_logger = logging.getLogger(__name__)


class SaleOrderPlugitRate(models.Model):
    _inherit = 'sale.order'

    # ── Root pricelist (traversed chain) ─────────────────────────────
    plugit_base_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Base Pricelist',
        compute='_compute_plugit_base_pricelist',
        store=True,
        readonly=True,
        help='Кореневий прайс-лист після обходу ланцюжка',
    )
    plugit_pricelist_currency_id = fields.Many2one(
        'res.currency',
        string='Base Pricelist Currency',
        related='plugit_base_pricelist_id.currency_id',
        store=True,
        readonly=True,
    )

    # ── Exchange rate ─────────────────────────────────────────────────
    plugit_rate = fields.Float(
        string='Pricelist Rate',
        digits=(16, 6),
        compute='_compute_plugit_rate',
        store=True,
        readonly=False,
        help='Скільки одиниць валюти замовлення за 1 одиницю базового прайс-листа',
    )
    plugit_rate_label = fields.Char(
        string='Rate',
        compute='_compute_plugit_rate_label',
        help='Відображення курсу у вигляді "41.50 UAH за 1 EUR"',
    )

    # ── Pending invoice update flag ───────────────────────────────────
    plugit_invoice_update_needed = fields.Boolean(
        string='Invoice Update Needed',
        default=False,
        copy=False,
        help='True — дата замовлення змінилась; інвойс ще не перераховано',
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

    @api.depends('plugit_pricelist_currency_id', 'currency_id', 'date_order')
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
                _logger.warning('Could not get conversion rate for order %s', order.name)
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

    # ── Track date changes → flag pending invoice update ─────────────

    def write(self, vals):
        old_dates = {o.id: o.date_order for o in self}
        result = super().write(vals)
        if 'date_order' in vals:
            for order in self:
                if (
                    order.date_order != old_dates.get(order.id)
                    and order.invoice_ids.filtered(lambda i: i.state != 'cancel')
                ):
                    order.plugit_invoice_update_needed = True
        return result

    # ── Copy rate to new invoice ──────────────────────────────────────

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['plugit_rate'] = self.plugit_rate
        return vals

    # ── Button: update linked invoice prices ─────────────────────────

    def action_plugit_update_invoice_prices(self):
        """Recalculate prices in all linked invoices using the current pricelist + date."""
        self.ensure_one()

        active_invoices = self.invoice_ids.filtered(lambda i: i.state != 'cancel')
        if not active_invoices:
            return

        pricelist = self.pricelist_id
        date = (
            self.date_order.date()
            if self.date_order
            else fields.Date.today()
        )

        for invoice in active_invoices:
            was_posted = invoice.state == 'posted'
            if was_posted:
                invoice.button_draft()

            line_updates = []
            for inv_line in invoice.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product' and l.sale_line_ids
            ):
                sale_line = inv_line.sale_line_ids[:1]
                product = sale_line.product_id
                uom = sale_line.product_uom_id
                qty = sale_line.product_uom_qty or 1.0

                if not pricelist or not product:
                    continue

                new_price = pricelist._get_product_price(
                    product,
                    qty,
                    currency=self.currency_id,
                    date=date,
                    uom=uom,
                )
                line_updates.append(Command.update(inv_line.id, {'price_unit': new_price}))

            if line_updates:
                invoice.write({'invoice_line_ids': line_updates})

            invoice.plugit_rate = self.plugit_rate

            if was_posted:
                invoice.action_post()

        self.plugit_invoice_update_needed = False
        self.message_post(
            body=_('Invoice prices recalculated. Rate: %.6f.', self.plugit_rate)
        )
