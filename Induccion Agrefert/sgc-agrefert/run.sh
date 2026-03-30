#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# SGC Agrefert — Sistema de Gestión de Calidad ISO 9001:2015
# ═══════════════════════════════════════════════════════════════════

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║   SGC AGREFERT — ISO 9001:2015               ║"
echo "  ║   Sistema de Gestión de Calidad               ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo ""

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 no está instalado."
    exit 1
fi

# Instalar dependencias si no están
echo "Verificando dependencias..."
pip3 install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt -q

echo ""
echo "Iniciando servidor..."
echo ""
echo "  Acceder a: http://localhost:5000"
echo ""
echo "  Credenciales iniciales:"
echo "  ──────────────────────"
echo "  Admin:    federico@agrefert.com / admin2026"
echo "  Equipo:   [email]@agrefert.com / agrefert2026"
echo ""
echo "  Para configurar alertas por email, definir variables:"
echo "  export MAIL_SERVER=smtp.gmail.com"
echo "  export MAIL_USERNAME=tu_email@gmail.com"
echo "  export MAIL_PASSWORD=tu_app_password"
echo ""

python3 app.py
