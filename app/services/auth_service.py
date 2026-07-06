import ldap3
from flask import current_app
from app.models import User
from app import db

class AuthService:
    """Servicio de autenticación con soporte LDAP y fallback local"""

    @staticmethod
    def authenticate(username, password):
        """Intenta autenticar por LDAP primero; si falla, por base de datos local."""
        # 1. Intentar LDAP si está habilitado
        if current_app.config.get('LDAP_ENABLED', False):
            user = AuthService.authenticate_ldap(username, password)
            if user:
                return user

        # 2. Fallback: autenticación local (solo usuarios con contraseña)
        return AuthService.authenticate_local(username, password)

    @staticmethod
    def authenticate_local(username, password):
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.is_active:
            return user
        return None

    @staticmethod
    def authenticate_ldap(username, password):
        try:
            ldap_server = current_app.config.get('LDAP_SERVER', 'dc.cairostudio.cu')
            ldap_base_dn = current_app.config.get('LDAP_BASE_DN', 'dc=cairostudio,dc=cu')
            ldap_domain = current_app.config.get('LDAP_DOMAIN', 'cairostudio.cu')

            user_principal = f'{username}@{ldap_domain}'
            server = ldap3.Server(ldap_server, get_info=ldap3.ALL)
            conn = ldap3.Connection(server, user=user_principal, password=password)

            if conn.bind():
                conn.search(
                    search_base=ldap_base_dn,
                    search_filter=f'(sAMAccountName={username})',
                    attributes=['displayName', 'mail', 'distinguishedName']
                )
                if conn.entries:
                    entry = conn.entries[0]
                    user = User.query.filter_by(username=username).first()
                    if not user:
                        user = User(
                            username=username,
                            email=entry.mail.value if entry.mail else None,
                            ldap_dn=entry.distinguishedName.value if entry.distinguishedName else None,
                            role='operario'
                        )
                        db.session.add(user)
                    else:
                        user.ldap_dn = entry.distinguishedName.value if entry.distinguishedName else None
                        user.email = entry.mail.value if entry.mail else None
                        user.is_active = True
                    db.session.commit()
                    return user
        except Exception as e:
            current_app.logger.error(f'Error en autenticación LDAP: {e}')
        return None

    @staticmethod
    def create_local_admin(username, password):
        if User.query.filter_by(username=username).first():
            raise ValueError(f'El usuario {username} ya existe')
        user = User(username=username, role='admin')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user
