import os
import hmac
import secrets

from datetime import timedelta

from flask import (
    Flask,
    redirect,
    url_for,
    render_template,
    request,
    session
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
# ENTORNO
# ============================================================

ES_RENDER = (
    os.environ.get(
        "RENDER",
        ""
    ).lower()
    == "true"
)


# ============================================================
# CLAVE SECRETA
# ============================================================

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "abc_business_manager_clave_secreta_2026"
)


# ============================================================
# CONFIGURACIÓN DE SESIÓN
# ============================================================
#
# La sesión dura 180 días.
#
# SESSION_REFRESH_EACH_REQUEST = True hace que mientras
# sigas utilizando ABC, la fecha de expiración se renueve.
#
# En Render:
#   Secure = True
#
# Localmente:
#   Secure = False
#
# para que siga funcionando con http://127.0.0.1:5000
# ============================================================

app.config.update(

    PERMANENT_SESSION_LIFETIME=
        timedelta(
            days=180
        ),

    SESSION_REFRESH_EACH_REQUEST=True,

    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_SECURE=ES_RENDER,

    SESSION_COOKIE_NAME=
        "abc_business_session"
)


# ============================================================
# CONTRASEÑA DE ABC
# ============================================================
#
# En Render debes crear:
#
# ABC_PASSWORD = tu contraseña
#
# Localmente, si no existe esa variable, se utilizará
# temporalmente:
#
# abc2026
#
# IMPORTANTE:
# En Render no permitimos iniciar si falta ABC_PASSWORD.
# ============================================================

ABC_PASSWORD = os.environ.get(
    "ABC_PASSWORD"
)


if ES_RENDER and not ABC_PASSWORD:

    raise RuntimeError(
        "Falta configurar ABC_PASSWORD "
        "en las variables de entorno de Render."
    )


if not ABC_PASSWORD:

    ABC_PASSWORD = "abc2026"


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
# PROTEGER TODA LA APLICACIÓN
# ============================================================

@app.before_request
def proteger_aplicacion():

    endpoint = (
        request.endpoint
        or ""
    )


    # --------------------------------------------------------
    # RUTAS PÚBLICAS
    # --------------------------------------------------------

    rutas_publicas = {
        "login",
        "static"
    }


    if endpoint in rutas_publicas:
        return None


    # --------------------------------------------------------
    # USUARIO YA AUTENTICADO
    # --------------------------------------------------------

    if session.get(
        "abc_autenticado"
    ):

        return None


    # --------------------------------------------------------
    # GUARDAR DESTINO ORIGINAL
    # --------------------------------------------------------

    if request.method == "GET":

        session[
            "abc_destino_despues_login"
        ] = request.full_path


    # --------------------------------------------------------
    # ENVIAR AL LOGIN
    # --------------------------------------------------------

    return redirect(
        url_for(
            "login"
        )
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=[
        "GET",
        "POST"
    ]
)
def login():

    # --------------------------------------------------------
    # SI YA ESTÁ AUTENTICADO
    # --------------------------------------------------------

    if session.get(
        "abc_autenticado"
    ):

        return redirect(
            url_for(
                "dashboard.index"
            )
        )


    error = None


    # ========================================================
    # TOKEN CSRF SIMPLE
    # ========================================================

    if (
        "abc_login_csrf"
        not in session
    ):

        session[
            "abc_login_csrf"
        ] = secrets.token_urlsafe(
            32
        )


    # ========================================================
    # POST
    # ========================================================

    if request.method == "POST":

        password = request.form.get(
            "password",
            ""
        )

        csrf_recibido = request.form.get(
            "csrf_token",
            ""
        )

        csrf_guardado = session.get(
            "abc_login_csrf",
            ""
        )


        # ----------------------------------------------------
        # VALIDAR CSRF
        # ----------------------------------------------------

        csrf_valido = (
            csrf_recibido
            and csrf_guardado
            and hmac.compare_digest(
                csrf_recibido,
                csrf_guardado
            )
        )


        if not csrf_valido:

            error = (
                "La sesión del formulario expiró. "
                "Actualiza la página e inténtalo de nuevo."
            )

        else:

            # ------------------------------------------------
            # VALIDAR CONTRASEÑA
            # ------------------------------------------------

            password_valido = (
                password
                and hmac.compare_digest(
                    password,
                    ABC_PASSWORD
                )
            )


            if password_valido:

                # --------------------------------------------
                # LIMPIAR SESIÓN VIEJA
                # --------------------------------------------

                destino = session.get(
                    "abc_destino_despues_login"
                )


                session.clear()


                # --------------------------------------------
                # CREAR SESIÓN AUTENTICADA
                # --------------------------------------------

                session.permanent = True

                session[
                    "abc_autenticado"
                ] = True


                # --------------------------------------------
                # REDIRECCIÓN
                # --------------------------------------------

                if (
                    destino
                    and destino.startswith("/")
                    and not destino.startswith("//")
                ):

                    return redirect(
                        destino
                    )


                return redirect(
                    url_for(
                        "dashboard.index"
                    )
                )


            error = (
                "Contraseña incorrecta."
            )


    # ========================================================
    # MOSTRAR LOGIN
    # ========================================================

    return render_template(
        "login.html",
        error=error,
        csrf_token=session[
            "abc_login_csrf"
        ]
    )


# ============================================================
# CERRAR SESIÓN
# ============================================================

@app.route(
    "/logout"
)
def logout():

    session.clear()

    return redirect(
        url_for(
            "login"
        )
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