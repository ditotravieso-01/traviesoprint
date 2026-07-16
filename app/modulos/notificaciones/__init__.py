from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.models import Notificacion, db

notificaciones_bp = Blueprint('notificaciones', __name__, url_prefix='/notificaciones')

@notificaciones_bp.route('/contar')
@login_required
def contar():
    total = Notificacion.query.filter_by(usuario_id=current_user.id, leida=False).count()
    return jsonify({'total': total})

@notificaciones_bp.route('/lista')
@login_required
def lista():
    notifs = Notificacion.query.filter_by(usuario_id=current_user.id).order_by(Notificacion.fecha_creacion.desc()).limit(20).all()
    data = [{
        'id': n.id,
        'mensaje': n.mensaje,
        'fecha': n.fecha_creacion.strftime('%d/%m/%Y %H:%M'),
        'leida': n.leida,
        'enlace': n.enlace
    } for n in notifs]
    return jsonify(data)

@notificaciones_bp.route('/marcar-leida/<int:notif_id>', methods=['POST'])
@login_required
def marcar_leida(notif_id):
    notif = Notificacion.query.get_or_404(notif_id)
    if notif.usuario_id != current_user.id:
        return jsonify({'error': 'No autorizado'}), 403
    notif.leida = True
    db.session.commit()
    return jsonify({'success': True})

@notificaciones_bp.route('/marcar-todas-leidas', methods=['POST'])
@login_required
def marcar_todas_leidas():
    Notificacion.query.filter_by(usuario_id=current_user.id, leida=False).update({'leida': True})
    db.session.commit()
    return jsonify({'success': True})