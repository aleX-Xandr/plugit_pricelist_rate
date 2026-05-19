from odoo import fields, models


class AccountMovePlugitRate(models.Model):
    _inherit = 'account.move'

    plugit_rate = fields.Float(
        string='Pricelist Rate',
        digits=(16, 6),
        readonly=True,
        copy=False,
        help='Курс базового прайс-листа до валюти інвойсу на дату замовлення (скопійовано із замовлення)',
    )
