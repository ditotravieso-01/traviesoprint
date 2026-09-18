import json
from datetime import datetime, timedelta
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
# MODELO DE CATEGORÍA (JERÁRQUICA)
# ==========================================
class Categoria(db.Model):
    __tablename__ = 'categorias'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(200))
    parent_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    es_material_impresion = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    children = db.relationship('Categoria', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')
    productos = db.relationship('Producto', back_populates='categoria', lazy=True)
    grupo_atributos = db.relationship('GrupoAtributos', backref='categoria', uselist=False, lazy=True)

    def __repr__(self):
        return f'<Categoria {self.nombre}>'

    def get_full_path(self):
        names = [self.nombre]
        parent = self.parent
        while parent:
            names.insert(0, parent.nombre)
            parent = parent.parent
        return ' > '.join(names)

    def get_descendant_ids(self):
        ids = []
        def get_children(parent):
            children = Categoria.query.filter_by(parent_id=parent.id).all()
            for child in children:
                ids.append(child.id)
                get_children(child)
        get_children(self)
        return ids

# ==========================================
# MODELO DE GRUPO DE ATRIBUTOS
# ==========================================
class GrupoAtributos(db.Model):
    __tablename__ = 'grupo_atributos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.String(255))
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    atributos = db.relationship('Atributo', backref='grupo', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<GrupoAtributos {self.nombre}>'

# ==========================================
# MODELO DE ATRIBUTO
# ==========================================
class Atributo(db.Model):
    __tablename__ = 'atributos'
    id = db.Column(db.Integer, primary_key=True)
    grupo_id = db.Column(db.Integer, db.ForeignKey('grupo_atributos.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    etiqueta = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)
    requerido = db.Column(db.Boolean, default=False)
    opciones = db.Column(db.Text, nullable=True)
    orden = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f'<Atributo {self.nombre} ({self.tipo})>'

# ==========================================
# MODELO DE ÁREA (OBSOLETO)
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
# MODELO DE TIPO DE PRODUCTO (OBSOLETO)
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
    ruta = db.Column(db.String(20), default='impresion')

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

    def get_tipos_archivos(self):
        """Devuelve lista única y ordenada de tipos de archivos: etiqueta, cartel, otro."""
        from collections import Counter
        tipos = []
        for a in self.archivos:
            params = a.get_parametros_etiqueta()
            if params is None:
                t = 'otro'
            else:
                t = params.get('tipo', 'etiqueta')  # params legacy sin 'tipo' = etiqueta
            tipos.append(t)
        c = Counter(tipos)
        orden_prioridad = ['etiqueta', 'cartel', 'otro']
        return [t for t in orden_prioridad if t in c]

    def get_proyecto_resumen(self):
        """Texto legible para la columna 'Proyecto': 'Etiquetas', 'Cartel', 'Etiquetas + Cartel'..."""
        tipos = self.get_tipos_archivos()
        if not tipos:
            return self.proyecto or '—'
        nombres = {'etiqueta': 'Etiquetas', 'cartel': 'Cartel', 'otro': 'Otros'}
        return ' + '.join(nombres[t] for t in tipos)

    def get_tipos_archivos(self):
        """Devuelve lista única y ordenada de tipos: ['etiqueta'], ['cartel', 'otro'], etc."""
        from collections import Counter
        tipos = []
        for a in self.archivos:
            params = a.get_parametros_etiqueta()
            t = 'otro' if params is None else params.get('tipo', 'etiqueta')
            tipos.append(t)
        c = Counter(tipos)
        return [t for t in ['etiqueta', 'cartel', 'otro'] if t in c]

    def get_proyecto_resumen(self):
        """Texto para el Kanban: 'Etiquetas', 'Cartel', 'Etiquetas + Cartel'."""
        tipos = self.get_tipos_archivos()
        if not tipos:
            return self.proyecto or '—'
        nombres = {'etiqueta': 'Etiquetas', 'cartel': 'Cartel', 'otro': 'Otros'}
        return ' + '.join(nombres[t] for t in tipos)

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
# MODELO DE PROVEEDOR (NUEVO)
# ==========================================
class Proveedor(db.Model):
    __tablename__ = 'proveedores'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    ruc = db.Column(db.String(50))
    telefono = db.Column(db.String(50))
    email = db.Column(db.String(100))
    direccion = db.Column(db.String(300))
    contacto = db.Column(db.String(100))
    notas = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    movimientos = db.relationship('Movimiento', backref='proveedor', lazy=True)

    def __repr__(self):
        return f'<Proveedor {self.nombre}>'

# ==========================================
# MODELO DE PRODUCTO (INVENTARIO)
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

    stock = db.Column(db.Float, default=0.0)
    stock_metros = db.Column(db.Float, default=0.0)
    stock_minimo = db.Column(db.Float, default=0.0)
    stock_comprometido = db.Column(db.Float, default=0.0)
    stock_comprometido_metros = db.Column(db.Float, default=0.0)

    fecha_vencimiento = db.Column(db.Date, nullable=True)
    ancho_rollo = db.Column(db.Float, nullable=True)
    merma_porcentaje = db.Column(db.Float, default=0.0)
    gap_panno_cm = db.Column(db.Float, default=6.5)  # cm entre paño y paño
    largo_rollo = db.Column(db.Float, nullable=True)
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
        return (self.stock_metros or 0) - (self.stock_comprometido_metros or 0)

    def get_stock_metros_total(self):
        return self.stock_metros or 0

    def get_stock_unidades_disponible(self):
        return (self.stock or 0) - (self.stock_comprometido or 0)

    def get_stock_unidades_total(self):
        return self.stock or 0

    def get_metros_por_unidad(self):
        return self.largo_rollo or 1.0

    def __repr__(self):
        return f'<Producto {self.nombre}>'

# ==========================================
# MODELO DE MOVIMIENTO (CON proveedor_id)
# ==========================================
class Movimiento(db.Model):
    __tablename__ = 'movimientos'
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)
    cantidad = db.Column(db.Float, nullable=False)
    cantidad_metros = db.Column(db.Float, nullable=True)
    costo_unitario = db.Column(db.Float, nullable=True)
    costo_total = db.Column(db.Float, nullable=True)
    comentario = db.Column(db.String(200), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=True)
    tipo_ajuste = db.Column(db.String(20), nullable=True)  # 'conteo' o 'correccion'

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
    cantidad_estimada = db.Column(db.Float, nullable=False, default=0.0)
    cantidad_real = db.Column(db.Float, nullable=True)
    orden = db.relationship('Order', backref='productos_asignados')
    producto = db.relationship('Producto', backref='ordenes_asignadas')

    def __repr__(self):
        return f'<OrdenProducto {self.orden_id} - {self.producto_id}>'

# ==========================================
# MODELOS DEL MÓDULO EMPLEADOS
# ==========================================
class Empleado(db.Model):
    __tablename__ = 'empleados'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    user = db.relationship('User', backref='empleado', uselist=False)
    numero_identificacion = db.Column(db.String(20), unique=True, nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    fecha_contratacion = db.Column(db.Date, nullable=True)
    tarifa_normal = db.Column(db.Float, default=1.00)
    tarifa_nocturna = db.Column(db.Float, default=1.30)
    tarifa_fin_semana = db.Column(db.Float, default=1.50)
    area = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    asistencias = db.relationship('Asistencia', backref='empleado', lazy='dynamic', cascade='all, delete-orphan')
    detalles_nomina = db.relationship('DetalleNomina', backref='empleado', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Empleado {self.user.username}>'

    def get_nomina_periodo(self, periodo_id):
        return self.detalles_nomina.filter_by(periodo_id=periodo_id).first()

    def get_asistencias_periodo(self, fecha_inicio, fecha_fin):
        return self.asistencias.filter(
            Asistencia.timestamp >= fecha_inicio,
            Asistencia.timestamp <= fecha_fin
        ).order_by(Asistencia.timestamp.asc()).all()

class Asistencia(db.Model):
    __tablename__ = 'asistencias'
    id = db.Column(db.Integer, primary_key=True)
    empleado_id = db.Column(db.Integer, db.ForeignKey('empleados.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.now)
    tipo = db.Column(db.String(10), nullable=False)
    comentario = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f'<Asistencia {self.empleado_id} {self.tipo} {self.timestamp}>'

class PeriodoNomina(db.Model):
    __tablename__ = 'periodos_nomina'
    id = db.Column(db.Integer, primary_key=True)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    estado = db.Column(db.String(20), default='abierto')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    detalles = db.relationship('DetalleNomina', backref='periodo', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<PeriodoNomina {self.fecha_inicio} - {self.fecha_fin}>'

    @classmethod
    def get_periodo_actual(cls):
        hoy = datetime.utcnow().date()
        dia = hoy.weekday()
        if dia >= 4:
            diff = dia - 4
        else:
            diff = dia + 3
        viernes = hoy - timedelta(days=diff)
        jueves = viernes + timedelta(days=6)
        return cls.query.filter_by(fecha_inicio=viernes, fecha_fin=jueves).first()

    @classmethod
    def crear_periodo_actual(cls):
        periodo = cls.get_periodo_actual()
        if not periodo:
            hoy = datetime.utcnow().date()
            dia = hoy.weekday()
            if dia >= 4:
                diff = dia - 4
            else:
                diff = dia + 3
            viernes = hoy - timedelta(days=diff)
            jueves = viernes + timedelta(days=6)
            periodo = cls(fecha_inicio=viernes, fecha_fin=jueves, estado='abierto')
            db.session.add(periodo)
            db.session.commit()
        return periodo

class DetalleNomina(db.Model):
    __tablename__ = 'detalles_nomina'
    id = db.Column(db.Integer, primary_key=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey('periodos_nomina.id'), nullable=False)
    empleado_id = db.Column(db.Integer, db.ForeignKey('empleados.id'), nullable=False)
    horas_totales = db.Column(db.Float, default=0.0)
    salario_bruto = db.Column(db.Float, default=0.0)
    aprobado = db.Column(db.Boolean, default=False)
    fecha_aprobacion = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f'<DetalleNomina {self.empleado_id} {self.periodo_id}>'

# ==========================================
# MODELO DE CONFIGURACIÓN
# ==========================================
class Configuracion(db.Model):
    __tablename__ = 'configuracion'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Configuracion {self.clave}={self.valor}>'

    @classmethod
    def get_config(cls, clave, default=None):
        registro = cls.query.filter_by(clave=clave).first()
        if registro:
            return registro.valor
        return default

    @classmethod
    def set_config(cls, clave, valor):
        registro = cls.query.filter_by(clave=clave).first()
        if registro:
            registro.valor = valor
        else:
            registro = cls(clave=clave, valor=valor)
            db.session.add(registro)
        db.session.commit()


# ==========================================
# MODELO DE PERMISOS (NUEVO PARA FASE 4)
# ==========================================
class Permiso(db.Model):
    __tablename__ = 'permisos'
    id = db.Column(db.Integer, primary_key=True)
    rol = db.Column(db.String(20), nullable=False)
    modulo = db.Column(db.String(30), nullable=False)
    permiso = db.Column(db.String(10), nullable=False)  # 'view' o 'edit'
    __table_args__ = (db.UniqueConstraint('rol', 'modulo', 'permiso', name='uq_permiso'),)

    def __repr__(self):
        return f'<Permiso {self.rol} {self.modulo} {self.permiso}>'

    @classmethod
    def get_role_permissions(cls, rol):
        """Devuelve dict {modulo: [permisos]} para un rol."""
        permisos = cls.query.filter_by(rol=rol).all()
        result = {}
        for p in permisos:
            if p.modulo not in result:
                result[p.modulo] = []
            result[p.modulo].append(p.permiso)
        return result

    @classmethod
    def has_permission(cls, rol, modulo, permiso):
        """Verifica si un rol tiene un permiso específico."""
        if rol == 'admin':
            return True
        return cls.query.filter_by(rol=rol, modulo=modulo, permiso=permiso).first() is not None

    @classmethod
    def set_permission(cls, rol, modulo, permiso, enabled):
        """Activa o desactiva un permiso."""
        if rol == 'admin':
            return
        if enabled:
            if not cls.query.filter_by(rol=rol, modulo=modulo, permiso=permiso).first():
                db.session.add(cls(rol=rol, modulo=modulo, permiso=permiso))
        else:
            cls.query.filter_by(rol=rol, modulo=modulo, permiso=permiso).delete()
        db.session.commit()

    @classmethod
    def init_default_permissions(cls):
        """Crea los permisos por defecto para roles no-admin."""
        defaults = {
            'operario': {
                'ordenes': ['view', 'edit'],
                'workflow': ['view'],
                'clientes': ['view'],
                'inventario': ['view'],
                'etiquetas': ['view'],
                'carteles': ['view'],
                'empleados': [],
                'usuarios': [],
                'configuracion': []
            },
            'disenador': {
                'ordenes': ['view', 'edit'],
                'workflow': ['view', 'edit'],
                'clientes': ['view'],
                'inventario': ['view'],
                'etiquetas': ['view', 'edit'],
                'carteles': ['view', 'edit'],
                'empleados': [],
                'usuarios': [],
                'configuracion': []
            },
            'comercial': {
                'ordenes': ['view', 'edit'],
                'workflow': ['view'],
                'clientes': ['view', 'edit'],
                'inventario': ['view'],
                'etiquetas': ['view'],
                'carteles': ['view'],
                'empleados': [],
                'usuarios': [],
                'configuracion': []
            },
            'economico': {
                'ordenes': ['view'],
                'workflow': ['view'],
                'clientes': ['view'],
                'inventario': ['view', 'edit'],
                'etiquetas': ['view'],
                'carteles': ['view'],
                'empleados': ['view'],
                'usuarios': [],
                'configuracion': []
            }
        }
        for rol, modulos in defaults.items():
            for modulo, permisos in modulos.items():
                for permiso in permisos:
                    if not cls.query.filter_by(rol=rol, modulo=modulo, permiso=permiso).first():
                        db.session.add(cls(rol=rol, modulo=modulo, permiso=permiso))
        db.session.commit()

# ==========================================
# MODELO DE EVENTO (CALENDARIO)
# ==========================================
class Evento(db.Model):
    __tablename__ = 'eventos'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    fecha_inicio = db.Column(db.DateTime, nullable=False)
    fecha_fin = db.Column(db.DateTime, nullable=True)
    tipo = db.Column(db.String(30), nullable=False, default='personalizado')
    color = db.Column(db.String(20), nullable=True)
    orden_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    orden = db.relationship('Order', backref='eventos')
    usuario = db.relationship('User', backref='eventos_creados')

    def __repr__(self):
        return f'<Evento {self.titulo}>'

    @classmethod
    def crear_desde_orden(cls, order):
        """Crea o actualiza un evento a partir de una orden."""
        if not order.fecha_entregado:
            # Si no hay fecha de entrega, eliminar evento asociado si existe
            evento = cls.query.filter_by(orden_id=order.id, tipo='entrega').first()
            if evento:
                db.session.delete(evento)
                db.session.commit()
            return
        
        # Buscar evento existente
        evento = cls.query.filter_by(orden_id=order.id, tipo='entrega').first()
        if evento:
            # Actualizar
            evento.fecha_inicio = order.fecha_entregado
            evento.fecha_fin = order.fecha_entregado + timedelta(hours=1)
            evento.titulo = f'Entrega: {order.order_num or "Orden"} - {order.client.nombre if order.client else "Sin cliente"}'
            evento.descripcion = order.descripcion or ''
            evento.color = '#f59e0b'  # color para entregas
        else:
            # Crear nuevo
            evento = cls(
                titulo=f'Entrega: {order.order_num or "Orden"} - {order.client.nombre if order.client else "Sin cliente"}',
                descripcion=order.descripcion or '',
                fecha_inicio=order.fecha_entregado,
                fecha_fin=order.fecha_entregado + timedelta(hours=1),
                tipo='entrega',
                color='#f59e0b',
                orden_id=order.id,
                usuario_id=order.created_by_id
            )
            db.session.add(evento)
        db.session.commit()
        return evento

    @classmethod
    def get_eventos_rango(cls, inicio, fin, usuario=None):
        """Obtiene eventos en un rango de fechas, opcionalmente filtrados por usuario."""
        query = cls.query.filter(
            cls.fecha_inicio >= inicio,
            cls.fecha_inicio <= fin
        )
        if usuario and usuario.role != 'admin':
            # Si no es admin, solo ver eventos que le pertenecen o que sean públicos
            query = query.filter(
                (cls.usuario_id == usuario.id) | (cls.tipo == 'entrega')
            )
        return query.all()

# ==========================================
# FUNCIÓN DE INICIALIZACIÓN DE CONFIGURACIÓN
# ==========================================
def init_configuracion():
    """Crea las claves de configuración por defecto si no existen."""
    from app import db
    claves_por_defecto = {
        'empresa_nombre': 'TraviesoPrint',
        'empresa_subtitulo': 'Gestión para talleres de impresión',
        'logo_url': 'img/logo_default.png',
        'login_bg_url': 'img/login_bg_default.jpg',
        'favicon_url': 'img/favicon_default.ico',
        'color_primario': '#1c1c1e',
        'color_secundario': '#a8854f',
        'instalacion_completada': 'false'
    }
    for clave, valor in claves_por_defecto.items():
        if not Configuracion.query.filter_by(clave=clave).first():
            config = Configuracion(clave=clave, valor=valor)
            db.session.add(config)
    db.session.commit()


class ConteoSemanal(db.Model):
    """
    Conteo semanal del económico.
    Registra el stock físico contado y calcula la merma imprevista
    (diferencia entre lo que el sistema dice y lo que se contó),
    descontando la merma operativa teórica de la semana.
    """
    __tablename__ = 'conteos_semanales'

    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey('productos.id'), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    fecha = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    semana = db.Column(db.String(10), nullable=False, index=True)  # "2026-W37"

    # Snapshot del sistema al momento del conteo
    stock_sistema_unidades = db.Column(db.Float, default=0.0)
    stock_sistema_metros = db.Column(db.Float, default=0.0)

    # Lo que el económico contó físicamente
    stock_fisico_unidades = db.Column(db.Float, default=0.0)
    stock_fisico_metros = db.Column(db.Float, default=0.0)

    # Diferencias (positivo = falta material)
    diferencia_unidades = db.Column(db.Float, default=0.0)
    diferencia_metros = db.Column(db.Float, default=0.0)

    # Merma operativa acumulada de la semana (desde parametros_etiqueta)
    merma_operativa_semana_m2 = db.Column(db.Float, default=0.0)

    # Merma imprevista = diferencia_metros*ancho - merma_operativa_semana
    merma_imprevista_metros = db.Column(db.Float, default=0.0)
    merma_imprevista_m2 = db.Column(db.Float, default=0.0)

    comentario = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    producto = db.relationship('Producto', backref=db.backref('conteos_semanales', lazy='dynamic'))
    usuario = db.relationship('User', backref='conteos_semanales')

    def __repr__(self):
        return f'<ConteoSemanal {self.semana} · {self.producto_id}>'

    @staticmethod
    def semana_iso(fecha=None):
        """Devuelve 'YYYY-Www' (ISO week)."""
        f = fecha or datetime.utcnow()
        iso = f.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    

# ==============================================================
# Clase etiquetas favoritas de cada cliente - modulo clientes
# ==============================================================
class EtiquetaFavorita(db.Model):
    """
    Etiqueta favorita de un cliente: medidas + archivo de referencia.
    Sirve como atajo al crear órdenes: el comercial ve las etiquetas
    guardadas del cliente y elige una sin tener que pedir medidas otra vez.
    """
    __tablename__ = 'etiquetas_favoritas'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)

    nombre = db.Column(db.String(150), nullable=False)
    ancho_cm = db.Column(db.Float, nullable=False)
    alto_cm = db.Column(db.Float, nullable=False)
    notas = db.Column(db.Text, nullable=True)

    # Archivo adjunto opcional (imagen o PDF)
    archivo_nombre = db.Column(db.String(255), nullable=True)
    archivo_ruta = db.Column(db.String(500), nullable=True)  # relativa a UPLOAD_FOLDER
    archivo_tipo = db.Column(db.String(80), nullable=True)   # mime
    archivo_tamano = db.Column(db.Integer, nullable=True)    # bytes

    # Métricas de uso
    veces_usado = db.Column(db.Integer, default=0, nullable=False)
    ultima_vez_usado = db.Column(db.DateTime, nullable=True)

    activo = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    client = db.relationship(
        'Client',
        backref=db.backref(
            'etiquetas_favoritas',
            lazy='dynamic',
            cascade='all, delete-orphan'
        )
    )
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<EtiquetaFavorita {self.nombre} ({self.ancho_cm}×{self.alto_cm}cm)>'

    def es_imagen(self):
        return bool(self.archivo_tipo and self.archivo_tipo.startswith('image/'))

    def es_pdf(self):
        return self.archivo_tipo == 'application/pdf'

    @property
    def archivo_tamano_mb(self):
        if not self.archivo_tamano:
            return None
        return round(self.archivo_tamano / (1024 * 1024), 2)

    @property
    def medidas_str(self):
        return f'{self.ancho_cm:g}×{self.alto_cm:g} cm'
    
    hash_archivo = db.Column(db.String(64), nullable=True, index=True)