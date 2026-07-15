import json
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager

# ==========================================
# MODELO DE USUARIO
# ==========================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='operario')
    ldap_dn = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

    def is_ldap_user(self):
        return self.ldap_dn is not None

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ==========================================
# MODELO DE ORDEN DE TRABAJO (con client_id)
# ==========================================
class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    order_num = db.Column(db.String(50), unique=True, nullable=False)
    date = db.Column(db.Date, nullable=False)
    # Relación con cliente
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    client = db.relationship('Client', backref='orders', lazy=True)
    # Otros campos
    solicitado = db.Column(db.String(100))
    proyecto = db.Column(db.String(100))
    invoice = db.Column(db.String(50))
    tipo_proyecto = db.Column(db.String(20), default='grafica')
    priority = db.Column(db.String(20), default='normal')
    servicios = db.Column(db.Text, default='[]')
    descripcion = db.Column(db.Text)
    column = db.Column(db.String(30), default='pendiente')
    entrada_ok = db.Column(db.Boolean, default=False)
    history = db.Column(db.Text, default='[]')
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    archivos = db.relationship('ArchivoAdjunto', backref='orden', lazy=True, cascade='all, delete-orphan')

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


# ==========================================
# MODELO DE ARCHIVO ADJUNTO
# ==========================================
class ArchivoAdjunto(db.Model):
    __tablename__ = 'archivo_adjunto'

    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    nombre_original = db.Column(db.String(255), nullable=False)
    nombre_visible = db.Column(db.String(255), nullable=False)
    material = db.Column(db.String(100), nullable=True)
    ruta = db.Column(db.String(500), nullable=True)
    cantidad = db.Column(db.Float, nullable=True)
    unidad = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'nombre_original': self.nombre_original,
            'nombre_visible': self.nombre_visible,
            'material': self.material,
            'ruta': self.ruta,
            'cantidad': self.cantidad,
            'unidad': self.unidad
        }


# ==========================================
# MODELO DE CLIENTES
# ==========================================
class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    referencia = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    telefono = db.Column(db.String(50))
    email = db.Column(db.String(120))
    direccion = db.Column(db.Text)
    etiquetas = db.Column(db.String(200))
    pedidos_venta = db.Column(db.Integer, default=0)
    total_facturado = db.Column(db.Float, default=0.0)
    gustos = db.Column(db.Text)
    notas = db.Column(db.Text)
    comercial = db.Column(db.String(100), nullable=True)
    carnet_identidad = db.Column(db.String(20))
    fecha_nacimiento = db.Column(db.Date)
    tipo_cliente = db.Column(db.String(30), default='persona')
    sector = db.Column(db.String(50))
    preferencias_diseno = db.Column(db.Text)
    metodo_pago_favorito = db.Column(db.String(30))
    referido_por = db.Column(db.String(100))
    frecuencia_pedido = db.Column(db.String(30))
    ultimo_pedido = db.Column(db.Date)
    observaciones_internas = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_by = db.relationship('User', foreign_keys=[created_by_id])