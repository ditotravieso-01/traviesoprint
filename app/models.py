import json
from datetime import datetime
from flask_login import UserMixin
from flask_login import current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
from datetime import datetime


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
    order_num = db.Column(db.String(50), unique=True, nullable=True)
    date = db.Column(db.Date, nullable=False)
    # Relación con cliente
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    client = db.relationship('Client', backref='orders', lazy=True)
    # Otros campos
    fecha_entregado = db.Column(db.DateTime, nullable=True)
    solicitado = db.Column(db.String(100))
    proyecto = db.Column(db.String(100))
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

    usuarios_notificados = db.Column(db.Text, default='[]')  # JSON con lista de IDs

    def get_usuarios_notificados(self):
        return json.loads(self.usuarios_notificados) if self.usuarios_notificados else []

    def set_usuarios_notificados(self, data):
        self.usuarios_notificados = json.dumps(data)

    def get_servicios(self):
        return json.loads(self.servicios) if self.servicios else []

    def set_servicios(self, data):
        self.servicios = json.dumps(data)

    def get_history(self):
        return json.loads(self.history) if self.history else []

    def add_history(self, entry):
        """Añade una entrada al historial.
        Si entry es un string, lo convierte a dict con fecha y usuario.
        """
        hist = self.get_history()
        if isinstance(entry, str):
            entry = {
                'mensaje': entry,
                'fecha': datetime.now().isoformat(),
                'usuario': current_user.username if hasattr(current_user, 'username') else 'Sistema'
            }
        elif isinstance(entry, dict):
            # Asegurar que tiene fecha
            if 'fecha' not in entry:
                entry['fecha'] = datetime.now().isoformat()
            if 'usuario' not in entry:
                entry['usuario'] = current_user.username if hasattr(current_user, 'username') else 'Sistema'
        hist.append(entry)
        self.history = json.dumps(hist)

    def get_history(self):
        return json.loads(self.history) if self.history else []
    
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
# MODELO DE NOTIFICACIONES
# ==========================================
class Notificacion(db.Model):
    __tablename__ = 'notificaciones'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    mensaje = db.Column(db.String(500), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # orden_creada, orden_editada, orden_estado
    leida = db.Column(db.Boolean, default=False)
    enlace = db.Column(db.String(200), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    
    usuario = db.relationship('User', foreign_keys=[usuario_id])
    orden = db.relationship('Order', foreign_keys=[order_id])
    
    def __repr__(self):
        return f'<Notificacion {self.id} - {self.usuario_id}>'


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


# ==========================================
# MODELO DE PRODUCTO (INVENTARIO)
# ==========================================
class Producto(db.Model):
    __tablename__ = 'productos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))  # tinta, vinilo, pvc, lona, etc.
    ubicacion = db.Column(db.String(50))  # almacen, garaje
    unidad = db.Column(db.String(20))  # rollo, bote, plancha, unidad
    costo = db.Column(db.Float, default=0.0)
    stock = db.Column(db.Float, default=0.0)
    stock_minimo = db.Column(db.Float, default=0.0)
    stock_comprometido = db.Column(db.Float, default=0.0)
    fecha_vencimiento = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Producto {self.nombre}>'

# ==========================================
# MODELO DE MOVIMIENTO (INVENTARIO)
# ==========================================
class Movimiento(db.Model):
    __tablename__ = 'movimientos'
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # entrada, consumo, salida_ajuste, entrada_ajuste
    cantidad = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    comentario = db.Column(db.String(200))
    orden_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    producto = db.relationship('Producto', backref='movimientos')
    orden = db.relationship('Order', backref='movimientos')
    usuario = db.relationship('User', backref='movimientos')

    def __repr__(self):
        return f'<Movimiento {self.id} - {self.tipo}>'