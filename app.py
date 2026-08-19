import os

from flask import (
    Flask,
    redirect,
    url_for
)

from database import obtener_conexion

from routes.clientes import clientes_bp
from routes.productos import productos_bp
from routes.pedidos import pedidos_bp
from routes.variantes import variantes_bp
from routes.inventario import inventario_bp
from routes.materiales import materiales_bp
from routes.compras import compras_bp
from routes.producciones import producciones_bp
from routes.finanzas import finanzas_bp
from routes.dashboard import dashboard_bp
from routes.reportes import reportes_bp
from routes.configuracion import configuracion_bp
from routes.agenda import agenda_bp
from routes.catalogo import catalogo_bp


# ============================================================
# CREAR APLICACIÓN
# ============================================================

app = Flask(__name__)


# ============================================================
# CLAVE SECRETA
# ============================================================
#
# En tu computadora, si no existe la variable SECRET_KEY,
# utilizará la clave local de respaldo.
#
# Cuando subamos ABC a Internet, configuraremos SECRET_KEY
# directamente en el servidor y no quedará escrita en GitHub.
# ============================================================

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "abc_business_manager_clave_secreta_2026"
)


# ============================================================
# BLUEPRINTS
# ============================================================

app.register_blueprint(
    clientes_bp
)

app.register_blueprint(
    productos_bp
)

app.register_blueprint(
    pedidos_bp
)

app.register_blueprint(
    inventario_bp
)

app.register_blueprint(
    materiales_bp
)

app.register_blueprint(
    variantes_bp
)

app.register_blueprint(
    compras_bp
)

app.register_blueprint(
    producciones_bp
)

app.register_blueprint(
    finanzas_bp
)

app.register_blueprint(
    dashboard_bp
)

app.register_blueprint(
    reportes_bp
)

app.register_blueprint(
    configuracion_bp
)

app.register_blueprint(
    agenda_bp
)

app.register_blueprint(
    catalogo_bp
)


# ============================================================
# PÁGINA PRINCIPAL
# ============================================================

@app.route("/")
def inicio():

    return redirect(
        url_for(
            "dashboard.index"
        )
    )


# ============================================================
# CONFIGURACIÓN GLOBAL DEL NEGOCIO
# ============================================================
#
# Esto permite usar configuracion_negocio en base.html
# y en las demás plantillas sin consultarla manualmente
# desde cada vista.
# ============================================================

@app.context_processor
def cargar_configuracion_negocio():

    conexion = None
    cursor = None

    try:

        conexion = obtener_conexion()

        cursor = conexion.cursor(
            dictionary=True
        )

        cursor.execute("""
            SELECT
                nombre_negocio,
                logo
            FROM configuracion_negocio
            ORDER BY id ASC
            LIMIT 1
        """)

        configuracion_negocio = (
            cursor.fetchone()
        )

    except Exception as e:

        print(
            "⚠️ No se pudo cargar la "
            "configuración del negocio:"
        )

        print(e)

        configuracion_negocio = None

    finally:

        if cursor:

            cursor.close()

        if conexion:

            conexion.close()


    return {
        "configuracion_negocio":
            configuracion_negocio
    }


# ============================================================
# EJECUCIÓN LOCAL
# ============================================================
#
# Este bloque solamente se utiliza cuando ejecutas:
#
# python app.py
#
# Cuando lo subamos a Render, Gunicorn cargará directamente:
#
# app:app
#
# y este bloque no se ejecutará.
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                "5000"
            )
        ),
        debug=True
    )