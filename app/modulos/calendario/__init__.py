from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.models import Evento, Order, User, db
from datetime import datetime, timedelta
from app.decorators import permission_required

calendario_bp = Blueprint('calendario', __name__, url_prefix='/calendario', template_folder='templates')


@calendario_bp.route('/')
@login_required
@permission_required('calendario', 'view')
def index():
    return render_template('calendario.html')


@calendario_bp.route('/evento/<int:evento_id>')
@login_required
@permission_required('calendario', 'view')
def detalle_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    # Verificar permisos: admin o creador o evento de entrega público
    if current_user.role != 'admin' and evento.usuario_id != current_user.id and evento.tipo != 'entrega':
        flash('No tienes permiso para ver este evento.', 'danger')
        return redirect(url_for('calendario.index'))
    
    return render_template('evento_detalle.html', evento=evento)


@calendario_bp.route('/eventos')
@login_required
@permission_required('calendario', 'view')
def get_eventos():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    try:
        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return jsonify([])
    
    eventos = Evento.get_eventos_rango(start, end, current_user)
    
    data = []
    for ev in eventos:
        data.append({
            'id': ev.id,
            'title': ev.titulo,
            'start': ev.fecha_inicio.isoformat(),
            'end': ev.fecha_fin.isoformat() if ev.fecha_fin else ev.fecha_inicio.isoformat(),
            'color': ev.color or '#3b82f6',
            'allDay': False,
            'extendedProps': {
                'tipo': ev.tipo,
                'descripcion': ev.descripcion,
                'orden_id': ev.orden_id,
                'usuario_id': ev.usuario_id,
                'url': url_for('ordenes.detalle_order', order_id=ev.orden_id) if ev.orden_id else None,
                'detalle_url': url_for('calendario.detalle_evento', evento_id=ev.id)
            }
        })
    return jsonify(data)


@calendario_bp.route('/eventos', methods=['POST'])
@login_required
@permission_required('calendario', 'edit')
def crear_evento():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos inválidos'}), 400
    
    titulo = data.get('titulo', '').strip()
    if not titulo:
        return jsonify({'error': 'El título es requerido'}), 400
    
    fecha_inicio = data.get('fecha_inicio')
    fecha_fin = data.get('fecha_fin')
    tipo = data.get('tipo', 'personalizado')
    color = data.get('color', '#3b82f6')
    descripcion = data.get('descripcion', '')
    
    try:
        inicio = datetime.fromisoformat(fecha_inicio.replace('Z', '+00:00'))
        fin = datetime.fromisoformat(fecha_fin.replace('Z', '+00:00')) if fecha_fin else inicio + timedelta(hours=1)
    except (ValueError, TypeError):
        return jsonify({'error': 'Formato de fecha inválido'}), 400
    
    evento = Evento(
        titulo=titulo,
        descripcion=descripcion,
        fecha_inicio=inicio,
        fecha_fin=fin,
        tipo=tipo,
        color=color,
        usuario_id=current_user.id
    )
    db.session.add(evento)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'id': evento.id,
        'start': evento.fecha_inicio.isoformat(),
        'end': evento.fecha_fin.isoformat() if evento.fecha_fin else evento.fecha_inicio.isoformat()
    })


@calendario_bp.route('/eventos/<int:evento_id>', methods=['PUT'])
@login_required
@permission_required('calendario', 'edit')
def editar_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    if current_user.role != 'admin' and evento.usuario_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Datos inválidos'}), 400
    
    if 'titulo' in data:
        evento.titulo = data['titulo'].strip()
    if 'descripcion' in data:
        evento.descripcion = data['descripcion']
    if 'fecha_inicio' in data:
        try:
            evento.fecha_inicio = datetime.fromisoformat(data['fecha_inicio'].replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return jsonify({'error': 'Formato de fecha inválido'}), 400
    if 'fecha_fin' in data:
        try:
            evento.fecha_fin = datetime.fromisoformat(data['fecha_fin'].replace('Z', '+00:00')) if data['fecha_fin'] else None
        except (ValueError, TypeError):
            return jsonify({'error': 'Formato de fecha inválido'}), 400
    if 'tipo' in data:
        evento.tipo = data['tipo']
    if 'color' in data:
        evento.color = data['color']
    
    db.session.commit()
    return jsonify({'success': True})


@calendario_bp.route('/eventos/<int:evento_id>', methods=['DELETE'])
@login_required
@permission_required('calendario', 'edit')
def eliminar_evento(evento_id):
    evento = Evento.query.get_or_404(evento_id)
    if current_user.role != 'admin' and evento.usuario_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403
    
    db.session.delete(evento)
    db.session.commit()
    return jsonify({'success': True})