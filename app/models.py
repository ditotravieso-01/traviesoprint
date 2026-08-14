import json
from datetime import datetime
from flask_login import UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager

# ==========================================
# MODELO DE USUARIO
# ==========================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
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
# MODELO DE ÁREA
# ==========================================
class Area(db.Model):
    __tablename__ = 'areas'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(200))
    tipo_atributos = db.Column(db.String(30), nullable=False, default='ninguno')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    productos = db.relationship('Producto', back_populates='area', lazy=True)

    def __repr__(self):
        return f'<Area {self.nombre}>'

# ==========================================
# MODELO DE CATEGORÍA
# ==========================================
class Categoria(db.Model):
    __tablename__ = 'categorias'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    productos = db.relationship('Producto', back_populates='categoria', lazy=True)

    def __repr__(self):
        return f'<Categoria {self.nombre}>'

# ==========================================
# MODELO DE UBICACIÓN
# ==========================================
class Ubicacion(db.Model):
    __tablename__ = 'ubicaciones'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    productos = db.relationship('Producto', back_populates='ubicacion_rel', lazy=True)

    def __repr__(self):
        return f'<Ubicacion {self.nombre}>'

# ==========================================
# MODELO DE TIPO DE PRODUCTO
# ==========================================
class TipoProducto(db.Model):
    __tablename__ = 'tipos_producto'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    productos = db.relationship('Producto', back_populates='tipo_rel', lazy=True)

    def __repr__(self):
        return f'<TipoProducto {self.nombre}>'

# ==========================================
# MODELO DE UNIDAD
# ==========================================
class Unidad(db.Model):
    __tablename__ = 'unidades'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    simbolo = db.Column(db.String(20), nullable=True)
    descripcion = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    productos = db.relationship('Producto', back_populates='unidad_rel', lazy=True)

    def __repr__(self):
        return f'<Unidad {self.nombre}>'

# ==========================================
# MODELO DE ORDEN DE TRABAJO
# ==========================================
class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    order_num = db.Column(db.String(50), unique=True, nullable=True)
    date = db.Column(db.Date, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    client = db.relationship('Client', backref='orders', lazy=True)
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
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    archivos = db.relationship('ArchivoAdjunto', backref='orden', lazy=True, cascade='all, delete-orphan')
    usuarios_notificados = db.Column(db.Text, default='[]')

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
        hist = self.get_history()
        if isinstance(entry, str):
            entry = {
                'mensaje': entry,
                'fecha': datetime.now().isoformat(),
                'usuario': current_user.username if hasattr(current_user, 'username') else 'Sistema'
            }
        elif isinstance(entry, dict):
            if 'fecha' not in entry:
                entry['fecha'] = datetime.now().isoformat()
            if 'usuario' not in entry:
                entry['usuario'] = current_user.username if hasattr(current_user, 'username') else 'Sistema'
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
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=True)
    parametros_etiqueta = db.Column(db.Text, nullable=True)
    producto = db.relationship('Producto', backref='archivos_asociados')

    def to_dict(self):
        return {
            'id': self.id,
            'nombre_original': self.nombre_original,
            'nombre_visible': self.nombre_visible,
            'material': self.material,
            'ruta': self.ruta,
            'cantidad': self.cantidad,
            'unidad': self.unidad,
            'producto_id': self.producto_id,
            'parametros_etiqueta': self.parametros_etiqueta
        }

    def get_parametros_etiqueta(self):
        return json.loads(self.parametros_etiqueta) if self.parametros_etiqueta else None

    def set_parametros_etiqueta(self, data):
        self.parametros_etiqueta = json.dumps(data) if data else None

# ==========================================
# MODELO DE NOTIFICACIONES
# ==========================================
class Notificacion(db.Model):
    __tablename__ = 'notificaciones'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    mensaje = db.Column(db.String(500), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
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
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_by = db.relationship('User', foreign_keys=[created_by_id])

# ==========================================
# MODELO DE PRODUCTO (INVENTARIO) - CON UNIDADES HÍBRIDAS
# ==========================================
class Producto(db.Model):
    __tablename__ = 'productos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, unique=True)
    descripcion = db.Column(db.Text, nullable=True)
    tipo = db.Column(db.String(50), nullable=True)
    ubicacion = db.Column(db.String(50), nullable=True)
    unidad = db.Column(db.String(20), nullable=True)
    costo = db.Column(db.Float, default=0.0)
    inversion_total = db.Column(db.Float, default=0.0)

    # STOCK EN UNIDADES FÍSICAS (rollos, litros, etc.)
    stock = db.Column(db.Float, default=0.0)
    # STOCK EN METROS (para materiales de impresión)
    stock_metros = db.Column(db.Float, default=0.0)

    stock_minimo = db.Column(db.Float, default=0.0)
    stock_comprometido = db.Column(db.Float, default=0.0)  # en unidades físicas
    stock_comprometido_metros = db.Column(db.Float, default=0.0)  # en metros

    fecha_vencimiento = db.Column(db.Date, nullable=True)
    ancho_rollo = db.Column(db.Float, nullable=True)
    largo_rollo = db.Column(db.Float, nullable=True)  # metros por rollo (factor de conversión)
    es_material_impresion = db.Column(db.Boolean, default=False, nullable=False)
    atributos_extra = db.Column(db.JSON, nullable=True, default={})

    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    area_id = db.Column(db.Integer, db.ForeignKey('areas.id'), nullable=True)
    ubicacion_id = db.Column(db.Integer, db.ForeignKey('ubicaciones.id'), nullable=True)
    tipo_producto_id = db.Column(db.Integer, db.ForeignKey('tipos_producto.id'), nullable=True)
    unidad_id = db.Column(db.Integer, db.ForeignKey('unidades.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categoria = db.relationship('Categoria', back_populates='productos')
    area = db.relationship('Area', back_populates='productos')
    ubicacion_rel = db.relationship('Ubicacion', back_populates='productos')
    tipo_rel = db.relationship('TipoProducto', back_populates='productos')
    unidad_rel = db.relationship('Unidad', back_populates='productos')
    movimientos = db.relationship('Movimiento', backref='producto', lazy='dynamic')

    def get_atributo(self, key, default=None):
        if self.atributos_extra:
            return self.atributos_extra.get(key, default)
        return default

    def set_atributo(self, key, value):
        if self.atributos_extra is None:
            self.atributos_extra = {}
        self.atributos_extra[key] = value

    def get_stock_metros_disponible(self):
        """Retorna el stock disponible en metros (stock_metros - comprometido_metros)"""
        return (self.stock_metros or 0) - (self.stock_comprometido_metros or 0)

    def get_stock_metros_total(self):
        """Retorna el stock total en metros"""
        return self.stock_metros or 0

    def get_stock_unidades_disponible(self):
        """Retorna el stock disponible en unidades físicas"""
        return (self.stock or 0) - (self.stock_comprometido or 0)

    def get_stock_unidades_total(self):
        """Retorna el stock total en unidades físicas"""
        return self.stock or 0

    def get_metros_por_unidad(self):
        """Retorna los metros por unidad física (largo_rollo)"""
        return self.largo_rollo or 1.0

    def __repr__(self):
        return f'<Producto {self.nombre}>'

# ==========================================
# MODELO DE MOVIMIENTO
# ==========================================
class Movimiento(db.Model):
    __tablename__ = 'movimientos'
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    cantidad_metros = db.Column(db.Float, nullable=True)  # para movimientos en metros
    costo_unitario = db.Column(db.Float, nullable=True)
    costo_total = db.Column(db.Float, nullable=True)
    comentario = db.Column(db.String(200), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)

    usuario = db.relationship('User', backref='movimientos')
    orden = db.relationship('Order', backref='movimientos')

    def __repr__(self):
        return f'<Movimiento {self.id} - {self.tipo}>'

# ==========================================
# MODELO DE RELACIÓN ORDEN-PRODUCTO
# ==========================================
class OrdenProducto(db.Model):
    __tablename__ = 'orden_producto'
    id = db.Column(db.Integer, primary_key=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    cantidad_estimada = db.Column(db.Float, nullable=False, default=0.0)  # en metros
    cantidad_real = db.Column(db.Float, nullable=True)  # en metros
    orden = db.relationship('Order', backref='productos_asignados')
    producto = db.relationship('Producto', backref='ordenes_asignadas')

    def __repr__(self):
        return f'<OrdenProducto {self.orden_id} - {self.producto_id}>'