from app.models import Notificacion, db
from flask import url_for

def crear_notificacion(usuario_id, mensaje, tipo, order_id=None, enlace=None):
    """Crea una notificación para un usuario específico"""
    notif = Notificacion(
        usuario_id=usuario_id,
        mensaje=mensaje,
        tipo=tipo,
        order_id=order_id,
        enlace=enlace
    )
    db.session.add(notif)
    db.session.commit()
    return notif

def notificar_usuarios(usuario_ids, mensaje, tipo, order_id=None, enlace=None):
    """Envía la misma notificación a múltiples usuarios (evita duplicados)"""
    # Usar set para eliminar duplicados
    usuario_ids = set(usuario_ids)
    for uid in usuario_ids:
        crear_notificacion(uid, mensaje, tipo, order_id, enlace)