import json
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager

# ==========================================
# MODELO DE USUARIO (con soporte LDAP)
# ==========================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=True)  # Solo para usuarios locales (admin)
    role = db.Column(db.String(20), nullable=False, default='operario')
    ldap_dn = db.Column(db.String(200), nullable=True)  # Distinguished Name en AD
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def set_password(self, password):
        """Establece contraseña (solo para usuarios locales)"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifica contraseña (solo usuarios locales)"""
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

    def is_ldap_user(self):
        """Indica si el usuario se autentica por LDAP"""
        return self.ldap_dn is not None

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


# ==========================================
# CARGA DE USUARIO PARA FLASK-LOGIN
# ==========================================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# MODELO DE ORDEN DE TRABAJO
# ==========================================
class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    order_num = db.Column(db.String(50), unique=True, nullable=False)  # N° de orden
    date = db.Column(db.Date, nullable=False)                         # Fecha de emisión
    client = db.Column(db.String(150), nullable=False)                # Cliente
    solicitado = db.Column(db.String(100))                            # Solicitado por
    proyecto = db.Column(db.String(100))                              # Proyecto/Producto
    invoice = db.Column(db.String(50))                                # Factura
    tipo_proyecto = db.Column(db.String(20), default='grafica')       # grafica, produccion, mixto, otro
    priority = db.Column(db.String(20), default='normal')             # urgente, normal, critica
    materiales = db.Column(db.Text, default='{}')                     # JSON con materiales y cantidades
    servicios = db.Column(db.Text, default='[]')                      # JSON con lista de servicios
    descripcion = db.Column(db.Text)                                  # Descripción (tamaño, sabor, etc.)
    incidencias = db.Column(db.Text)                                  # Incidencias
    column = db.Column(db.String(30), default='pendiente')            # Columna actual del flujo
    entrada_ok = db.Column(db.Boolean, default=False)                 # Si se marcó entrada al sistema
    history = db.Column(db.Text, default='[]')                        # JSON con historial de acciones
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # Relación con usuario (opcional pero útil)
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __init__(self, **kwargs):
        super(Order, self).__init__(**kwargs)
        # Asegurar que los campos JSON sean válidos
        if isinstance(self.materiales, dict):
            self.materiales = json.dumps(self.materiales)
        if isinstance(self.servicios, list):
            self.servicios = json.dumps(self.servicios)
        if isinstance(self.history, list):
            self.history = json.dumps(self.history)

    def get_materiales(self):
        return json.loads(self.materiales) if self.materiales else {}

    def set_materiales(self, data):
        self.materiales = json.dumps(data)

    def get_servicios(self):
        return json.loads(self.servicios) if self.servicios else []

    def set_servicios(self, data):
        self.servicios = json.dumps(data)

    def get_history(self):
        return json.loads(self.history) if self.history else []

    def add_history(self, entry):
        hist = self.get_history()
        hist.append(entry)
        self.history = json.dumps(hist)

    def __repr__(self):
        return f'<Order {self.order_num}>'
    
