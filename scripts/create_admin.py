#!/usr/bin/env python3
"""
Script para crear un usuario administrador local (emergencia).
Ejecutar: python scripts/create_admin.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.services.auth_service import AuthService

app = create_app()
with app.app_context():
    print("=== Crear usuario administrador local (fallback) ===")
    username = input("Usuario: ").strip()
    if not username:
        print("❌ Nombre de usuario requerido.")
        sys.exit(1)
    password = input("Contraseña: ").strip()
    if not password:
        print("❌ Contraseña requerida.")
        sys.exit(1)

    try:
        user = AuthService.create_local_admin(username, password)
        print(f"✅ Usuario admin '{username}' creado correctamente.")
    except ValueError as e:
        print(f"❌ Error: {e}")
