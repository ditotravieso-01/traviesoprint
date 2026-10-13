"""
Servicio de integración con Odoo ERP vía XML-RPC.

Autenticación nativa de Odoo: usuario + API key via `common.authenticate`.

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

        Filtra por type='contact' y excluye empleados y partners inactivos.

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
        Devuelve ventas confirmadas (sale.order state='sale') con la
        información de `user_id` y `create_uid` enriquecida con name + email.

        Para cada venta devuelve además:
            user_id_name      : nombre display del comercial
            user_id_email     : email/login del comercial (para matching)
            create_uid_name   : nombre display de quien creó el registro
        """
        if desde is None:
            raise ValueError('get_ventas_confirmadas: falta "desde"')

        desde_str = desde.strftime('%Y-%m-%d %H:%M:%S')

        kwargs = {
            'fields': [
                'id', 'name', 'date_order', 'partner_id',
                'note', 'user_id', 'commitment_date', 'create_uid',
            ],
            'order': 'date_order asc',
        }
        if limit:
            kwargs['limit'] = limit

        domain = [
            ['state', '=', 'sale'],
            ['date_order', '>=', desde_str],
        ]

        ventas = self.models.execute_kw(
            self.db, self.uid, self.password,
            'sale.order', 'search_read',
            [domain],
            kwargs,
        )

        # Recoger ids únicos de user_id y create_uid
        user_ids = set()
        for v in ventas:
            uid_pair = v.get('user_id') or []
            if isinstance(uid_pair, (list, tuple)) and uid_pair:
                user_ids.add(uid_pair[0])
            cuid_pair = v.get('create_uid') or []
            if isinstance(cuid_pair, (list, tuple)) and cuid_pair:
                user_ids.add(cuid_pair[0])

        # Leer todos los users de una vez y mapear por id
        users_map = {}
        if user_ids:
            try:
                usuarios = self.models.execute_kw(
                    self.db, self.uid, self.password,
                    'res.users', 'read',
                    [list(user_ids)],
                    {'fields': ['id', 'name', 'login', 'email']},
                )
                for u in usuarios:
                    users_map[u['id']] = u
            except Exception:
                # Si falla la lectura, seguimos sin emails (degrada, no rompe)
                users_map = {}

        # Enriquecer cada venta
        for v in ventas:
            uid_pair = v.get('user_id') or []
            if isinstance(uid_pair, (list, tuple)) and uid_pair:
                u = users_map.get(uid_pair[0], {})
                v['user_id_name'] = u.get('name') or (uid_pair[1] if len(uid_pair) > 1 else None)
                v['user_id_email'] = (u.get('email') or u.get('login') or '').strip() or None
            else:
                v['user_id_name'] = None
                v['user_id_email'] = None

            cuid_pair = v.get('create_uid') or []
            if isinstance(cuid_pair, (list, tuple)) and cuid_pair:
                u = users_map.get(cuid_pair[0], {})
                v['create_uid_name'] = u.get('name') or (cuid_pair[1] if len(cuid_pair) > 1 else None)
            else:
                v['create_uid_name'] = None

        return ventas