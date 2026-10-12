"""
Servicio de integración con Odoo ERP vía XML-RPC.

Uso:
    from app.services.odoo_service import OdooService
    service = OdooService()
    clientes = service.get_clientes()

Requiere que existan las siguientes variables en config (que a su vez
vienen del .env):
    ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD

Si ODOO_ENABLED=False en config, no se debe instanciar este servicio.
"""
import xmlrpc.client
from flask import current_app


class OdooService:
    """Cliente XML-RPC contra Odoo. Solo lectura por ahora."""

    def __init__(self):
        cfg = current_app.config
        self.url = cfg.get('ODOO_URL', '')
        self.db = cfg.get('ODOO_DB', '')
        self.user = cfg.get('ODOO_USER', '')
        self.password = cfg.get('ODOO_PASSWORD', '')
        self.uid = None
        self.models = None
        self._connect()

    def _connect(self):
        """Autentica contra Odoo y prepara el cliente de objetos."""
        if not all([self.url, self.db, self.user, self.password]):
            raise RuntimeError(
                'OdooService: faltan credenciales. '
                'Revisa ODOO_URL, ODOO_DB, ODOO_USER y ODOO_PASSWORD en el .env'
            )
        common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
        self.uid = common.authenticate(self.db, self.user, self.password, {})
        if not self.uid:
            raise RuntimeError(
                'OdooService: autenticación fallida. '
                'Revisa ODOO_USER y ODOO_PASSWORD'
            )
        self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')

    def get_clientes(self, limit=None):
        """
        Devuelve lista de clientes desde Odoo.

        Filtra por customer_rank > 0 para excluir proveedores y contactos
        que no son clientes.

        Args:
            limit: opcional, máximo de registros a devolver.

        Returns:
            Lista de dicts con claves: id, name, email, phone, street, city, vat, ref
        """
        kwargs = {
            'fields': ['id', 'name', 'email', 'phone', 'street', 'city', 'vat', 'ref']
        }
        if limit:
            kwargs['limit'] = limit

        return self.models.execute_kw(
            self.db, self.uid, self.password,
            'res.partner', 'search_read',
            [[['type', '=', 'contact'], ['employee', '=', False], ['active', '=', True]]],
            kwargs
        )

    def get_ventas_confirmadas(self, desde, limit=200):
        """
        Devuelve ventas confirmadas (sale.order con state='sale') cuya
        date_order sea >= 'desde'.

        Args:
            desde: datetime UTC (naive) — punto de corte inferior.
            limit: opcional, máximo de registros.

        Returns:
            Lista de dicts con: id, name, date_order, partner_id,
            note, user_id, commitment_date. Ordenada por date_order asc.

        Notas:
            - Solo lectura. No modifica nada en Odoo.
            - 'date_order' en Odoo es UTC; 'desde' debe venir en UTC naive.
            - No captura excepciones: el caller (sync-odoo) decide qué hacer.
        """
        if desde is None:
            raise ValueError('get_ventas_confirmadas: falta "desde"')

        desde_str = desde.strftime('%Y-%m-%d %H:%M:%S')

        kwargs = {
            'fields': [
                'id', 'name', 'date_order', 'partner_id',
                'note', 'user_id', 'commitment_date',
            ],
            'order': 'date_order asc',
        }
        if limit:
            kwargs['limit'] = limit

        domain = [
            ['state', '=', 'sale'],
            ['date_order', '>=', desde_str],
        ]

        return self.models.execute_kw(
            self.db, self.uid, self.password,
            'sale.order', 'search_read',
            [domain],
            kwargs,
        )
