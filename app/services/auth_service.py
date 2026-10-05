import ssl
import ldap3
from flask import current_app
from app.models import User
from app import db


class AuthService:
    """Servicio de autenticación con soporte LDAPS + fallback local."""

    # =========================================================
    # PÚBLICO
    # =========================================================
    @staticmethod
    def authenticate(username, password):
        """Intenta LDAP primero; si falla, cae a auth local."""
        if not username or not password:
            return None

        if current_app.config.get('LDAP_ENABLED', False):
            user = AuthService.authenticate_ldap(username, password)
            if user:
                return user

        return AuthService.authenticate_local(username, password)

    # =========================================================
    # LOCAL
    # =========================================================
    @staticmethod
    def authenticate_local(username, password):
        user = User.query.filter_by(username=username).first()
        # Solo usuarios que tengan password local (evita que un user AD sin pass matchee)
        if not user or not user.password_hash:
            return None
        if user.check_password(password) and user.is_active:
            return user
        return None

    # =========================================================
    # LDAP / LDAPS
    # =========================================================
    @staticmethod
    def _clean_sam(username):
        """Normaliza el username a sAMAccountName puro.
        'CAIROSTUDIO\\eduardo'    -> 'eduardo'
        'eduardo@cairostudio.cu'  -> 'eduardo'
        'EDUARDO'                 -> 'eduardo'
        """
        u = (username or '').strip()
        if '\\' in u:
            u = u.split('\\', 1)[1]
        if '@' in u:
            u = u.split('@', 1)[0]
        return u.lower()

    @staticmethod
    def authenticate_ldap(username, password):
        cfg = current_app.config
        ldap_server = cfg.get('LDAP_SERVER')
        ldap_port = cfg.get('LDAP_PORT', 636)
        ldap_use_ssl = cfg.get('LDAP_USE_SSL', True)
        ldap_base_dn = cfg.get('LDAP_BASE_DN')
        ldap_domain = cfg.get('LDAP_DOMAIN')
        ldap_timeout = cfg.get('LDAP_TIMEOUT', 5)
        ca_certs = cfg.get('LDAP_CA_CERTS')
        service_user = cfg.get('LDAP_SERVICE_USER')
        service_password = cfg.get('LDAP_SERVICE_PASSWORD')

        sam = AuthService._clean_sam(username)
        if not sam or not password:
            return None

        # Dos conexiones: una con el usuario (valida password), otra como servicio (lee atributos)
        # AD permite buscar con el propio bind del usuario, así que usamos solo una.
        user_principal = f'{sam}@{ldap_domain}'

        try:
            tls = ldap3.Tls(
                validate=ssl.CERT_REQUIRED,
                ca_certs_file=ca_certs,
                version=ssl.PROTOCOL_TLS_CLIENT,
            )
            server = ldap3.Server(
                ldap_server,
                port=ldap_port,
                use_ssl=ldap_use_ssl,
                tls=tls,
                get_info=ldap3.NONE,
                connect_timeout=ldap_timeout,
            )

            conn = ldap3.Connection(
                server,
                user=user_principal,
                password=password,
                auto_bind=True,
                raise_exceptions=False,
                receive_timeout=ldap_timeout,
            )

            if not conn.bound:
                current_app.logger.info(f'LDAP bind fallido para {sam}: {conn.result}')
                return None

            try:
                conn.search(
                    search_base=ldap_base_dn,
                    search_filter=f'(sAMAccountName={sam})',
                    attributes=['displayName', 'mail', 'distinguishedName', 'memberOf'],
                )

                if not conn.entries:
                    current_app.logger.warning(f'LDAP bind OK pero sin entrada para {sam}')
                    return None

                entry = conn.entries[0]

                # Buscar o crear User local
                user = User.query.filter_by(username=sam).first()
                if not user:
                    user = User(username=sam, role='operario', is_active=True)
                    db.session.add(user)

                # Refrescar datos desde AD
                if entry.mail:
                    user.email = entry.mail.value
                if entry.distinguishedName:
                    user.ldap_dn = entry.distinguishedName.value
                user.is_active = True

                db.session.commit()
                return user

            finally:
                conn.unbind()

        except ldap3.core.exceptions.LDAPSocketOpenError as e:
            current_app.logger.error(f'No se pudo conectar a LDAPS {ldap_server}:{ldap_port}: {e}')
            return None
        except ldap3.core.exceptions.LDAPException as e:
            current_app.logger.error(f'Error LDAP: {e}')
            return None
        except Exception as e:
            current_app.logger.error(f'Error inesperado en LDAP: {e}', exc_info=True)
            return None

    # =========================================================
    # UTILIDAD
    # =========================================================
    @staticmethod
    def create_local_admin(username, password):
        if User.query.filter_by(username=username).first():
            raise ValueError(f'El usuario {username} ya existe')
        user = User(username=username, role='admin')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user