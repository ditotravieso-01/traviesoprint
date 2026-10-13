"""
Servicio de integración con Odoo ERP vía XML-RPC.

Autenticación: módulo OCA `auth_api_key`. La clave se envía
en el header HTTP `API-KEY`, no via `common.authenticate`.

Requiere en .env:
    ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD, ODOO_UID

Si ODOO_ENABLED=False en config, no se debe instanciar este servicio.
"""
import os
import xmlrpc.client
from flask import current_app


class _ApiKeyTransport(xmlrpc.client.Transport):
    """
    Transport XML-RPC que añade el header `API-KEY` a cada petición.

    Necesario para el módulo OCA `auth_api_key`, que autentica
    por header HTTP en lugar de por `common.authenticate()`.
    """

    def __init__(self, api_key, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_key = api_key or ''

    def send_headers(self, connection, headers):
        if self._api_key:
            connection.putheader('API-KEY', self._api_key)
        super().send_headers(connection, headers)


class OdooService:
    """Cliente XML-RPC contra Odoo. Solo lectura por ahora."""

    def __init__(self):
        cfg = current_app.config
        self.url = cfg.get('ODOO_URL', '')
        self.db = cfg.get('ODOO_DB', '')
        self.user = cfg.get('ODOO_USER', '')
        self.password = cfg.get('ODOO_PASSWORD', '')
        self.uid_env = cfg.get('ODOO_UID', '')
        self.uid = None
        self.models = None
        self._connect()

    def _connect(self):
        """Prepara el cliente XML-RPC usando el header API-KEY."""
        if not all([self.url, self.db, self.user, self.password]):
            raise RuntimeError(
                'OdooService: faltan credenciales. '
                'Revisa ODOO_URL, ODOO_DB, ODOO_USER y ODOO_PASSWORD en el .env'
            )

        # UID explícito — el módulo OCA no expone `common.authenticate`.
        if not str(self.uid_env).strip():
            raise RuntimeError(
                'OdooService: falta ODOO_UID en el .env. '
                'Es el id numérico del usuario robot en Odoo (ej. 7). '
                'Míralo en la URL del usuario: /odoo/settings/users/<id>'
            )
        try:
            self.uid = int(self.uid_env)
        except (ValueError, TypeError):
            raise RuntimeError(
                f'OdooService: ODOO_UID inválido: {self.uid_env!r}. '
                'Debe ser un número entero.'
            )

        # Cliente XML-RPC con header API-KEY inyectado
        transport = _ApiKeyTransport(self.password)
        self.models = xmlrpc.client.ServerProxy(
            f'{self.url}/xmlrpc/2/object',
            transport=transport,
        )

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
            limit: máximo de registros (default 200).

        Returns:
            Lista de dicts con: id, name, date_order, partner_id,
            note, user_id, commitment_date. Ordenada por date_order asc.
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