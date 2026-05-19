{
    'name': 'Plugit. Pricelist Rate',
    'version': '19.0.1.0.0',
    'summary': 'Зберігає курс між базовим прайс-листом і валютою замовлення, передає в інвойс',
    'description': """
        - Обходить ланцюжок прайс-листів до кореневого
        - Визначає валюту кореневого прайсу
        - Обчислює та зберігає курс до валюти замовлення на дату замовлення
        - Копіює курс в інвойс при виставленні
        - Кнопка «Оновити ціни інвойсу» оновлює рядки та суми пов'язаного інвойсу
    """,
    'category': 'Sales',
    'author': 'Plugit',
    'license': 'LGPL-3',
    'depends': ['sale', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
