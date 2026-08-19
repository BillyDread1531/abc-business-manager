import os

from decimal import Decimal, InvalidOperation

from werkzeug.utils import secure_filename

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app
)

from database import obtener_conexion


configuracion_bp = Blueprint(
    "configuracion",
    __name__,
    url_prefix="/configuracion"
)


# ============================================================
# CONFIGURACIÓN DE LOGO
# ============================================================

EXTENSIONES_LOGO = {
    "png",
    "jpg",
    "jpeg",
    "webp"
}


def extension_logo_permitida(nombre_archivo):

    if not nombre_archivo:
        return False

    if "." not in nombre_archivo:
        return False

    extension = (
        nombre_archivo
        .rsplit(".", 1)[1]
        .lower()
    )

    return extension in EXTENSIONES_LOGO


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

@configuracion_bp.route("/", methods=["GET", "POST"])
def index():

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    try:

        # ====================================================
        # CARGAR CONFIGURACIÓN ACTUAL
        # ====================================================

        cursor.execute("""
            SELECT *
            FROM configuracion_negocio
            ORDER BY id ASC
            LIMIT 1
        """)

        configuracion = cursor.fetchone()


        # ====================================================
        # GUARDAR CAMBIOS
        # ====================================================

        if request.method == "POST":

            nombre_negocio = request.form.get(
                "nombre_negocio",
                ""
            ).strip()

            telefono = request.form.get(
                "telefono",
                ""
            ).strip() or None

            whatsapp = request.form.get(
                "whatsapp",
                ""
            ).strip() or None

            email = request.form.get(
                "email",
                ""
            ).strip() or None

            direccion = request.form.get(
                "direccion",
                ""
            ).strip() or None

            moneda = request.form.get(
                "moneda",
                "GTQ"
            ).strip()

            prefijo_pedido = request.form.get(
                "prefijo_pedido",
                "PED-"
            ).strip()

            porcentaje_anticipo = request.form.get(
                "porcentaje_anticipo",
                "60"
            ).strip()

            dias_vigencia_cotizacion = request.form.get(
                "dias_vigencia_cotizacion",
                "7"
            ).strip()

            banco = request.form.get(
                "banco",
                ""
            ).strip() or None

            tipo_cuenta = request.form.get(
                "tipo_cuenta",
                ""
            ).strip() or None

            numero_cuenta = request.form.get(
                "numero_cuenta",
                ""
            ).strip() or None

            titular_cuenta = request.form.get(
                "titular_cuenta",
                ""
            ).strip() or None

            notas_pago = request.form.get(
                "notas_pago",
                ""
            ).strip() or None

            porcentaje_propietario_texto = request.form.get(
                "porcentaje_propietario",
                "50"
            ).strip()

            porcentaje_reinversion_texto = request.form.get(
                "porcentaje_reinversion",
                "30"
            ).strip()

            porcentaje_reserva_texto = request.form.get(
                "porcentaje_reserva",
                "20"
            ).strip()

            logo_archivo = request.files.get(
                "logo"
            )


            # =================================================
            # VALIDACIONES
            # =================================================

            if not nombre_negocio:

                raise ValueError(
                    "El nombre del negocio es obligatorio."
                )


            if not prefijo_pedido:

                raise ValueError(
                    "El prefijo de pedidos no puede quedar vacío."
                )


            # -------------------------------------------------
            # Anticipo
            # -------------------------------------------------

            try:

                porcentaje_anticipo = float(
                    porcentaje_anticipo
                )

            except ValueError:

                raise ValueError(
                    "El porcentaje de anticipo no es válido."
                )


            if porcentaje_anticipo < 0:

                raise ValueError(
                    "El anticipo no puede ser menor que 0%."
                )


            if porcentaje_anticipo > 100:

                raise ValueError(
                    "El anticipo no puede ser mayor que 100%."
                )


            # -------------------------------------------------
            # Vigencia de cotización
            # -------------------------------------------------

            try:

                dias_vigencia_cotizacion = int(
                    dias_vigencia_cotizacion
                )

            except ValueError:

                raise ValueError(
                    "La vigencia de la cotización debe ser un número entero."
                )


            if dias_vigencia_cotizacion < 1:

                raise ValueError(
                    "La vigencia debe ser de al menos 1 día."
                )


            if dias_vigencia_cotizacion > 365:

                raise ValueError(
                    "La vigencia no puede superar 365 días."
                )


            # -------------------------------------------------
            # Moneda
            # -------------------------------------------------

            monedas_validas = {
                "GTQ",
                "USD"
            }


            if moneda not in monedas_validas:

                raise ValueError(
                    "La moneda seleccionada no es válida."
                )


            # -------------------------------------------------
            # Distribución de utilidades
            # -------------------------------------------------

            try:

                porcentaje_propietario = Decimal(
                    porcentaje_propietario_texto
                )

                porcentaje_reinversion = Decimal(
                    porcentaje_reinversion_texto
                )

                porcentaje_reserva = Decimal(
                    porcentaje_reserva_texto
                )

            except InvalidOperation:

                raise ValueError(
                    "Los porcentajes de distribución de utilidades "
                    "deben ser números válidos."
                )

            porcentajes_utilidad = (
                porcentaje_propietario,
                porcentaje_reinversion,
                porcentaje_reserva
            )

            if any(
                porcentaje < 0
                or porcentaje > 100
                for porcentaje in porcentajes_utilidad
            ):

                raise ValueError(
                    "Cada porcentaje de distribución debe estar "
                    "entre 0% y 100%."
                )

            total_distribucion = sum(
                porcentajes_utilidad,
                Decimal("0")
            )

            if total_distribucion != Decimal("100"):

                raise ValueError(
                    "La distribución de utilidades debe sumar "
                    "exactamente 100%."
                )

            # =================================================
            # LOGO ACTUAL
            # =================================================

            nuevo_logo = (
                configuracion["logo"]
                if configuracion
                else None
            )


            # =================================================
            # SUBIR NUEVO LOGO
            # =================================================

            if (
                logo_archivo
                and
                logo_archivo.filename
            ):

                if not extension_logo_permitida(
                    logo_archivo.filename
                ):

                    raise ValueError(
                        "El logo debe ser PNG, JPG, JPEG o WEBP."
                    )


                nombre_original = secure_filename(
                    logo_archivo.filename
                )


                extension = (
                    nombre_original
                    .rsplit(".", 1)[1]
                    .lower()
                )


                nombre_logo = (
                    f"logo_negocio.{extension}"
                )


                carpeta_uploads = os.path.join(
                    current_app.root_path,
                    "static",
                    "uploads"
                )


                os.makedirs(
                    carpeta_uploads,
                    exist_ok=True
                )


                # ------------------------------------------------
                # Eliminar logo anterior si tenía otra extensión
                # ------------------------------------------------

                if nuevo_logo:

                    ruta_logo_anterior = os.path.join(
                        current_app.root_path,
                        "static",
                        nuevo_logo
                    )


                    if (
                        os.path.isfile(
                            ruta_logo_anterior
                        )
                        and
                        os.path.basename(
                            ruta_logo_anterior
                        )
                        != nombre_logo
                    ):

                        try:

                            os.remove(
                                ruta_logo_anterior
                            )

                        except OSError:

                            pass


                ruta_logo = os.path.join(
                    carpeta_uploads,
                    nombre_logo
                )


                logo_archivo.save(
                    ruta_logo
                )


                nuevo_logo = (
                    f"uploads/{nombre_logo}"
                )


            # =================================================
            # ACTUALIZAR REGISTRO EXISTENTE
            # =================================================

            if configuracion:

                cursor.execute("""
                    UPDATE configuracion_negocio
                    SET
                        nombre_negocio = %s,
                        logo = %s,
                        telefono = %s,
                        whatsapp = %s,
                        email = %s,
                        direccion = %s,
                        moneda = %s,
                        prefijo_pedido = %s,
                        porcentaje_anticipo = %s,
                        dias_vigencia_cotizacion = %s,
                        banco = %s,
                        tipo_cuenta = %s,
                        numero_cuenta = %s,
                        titular_cuenta = %s,
                        notas_pago = %s,
                        porcentaje_propietario = %s,
                        porcentaje_reinversion = %s,
                        porcentaje_reserva = %s
                    WHERE id = %s
                """, (
                    nombre_negocio,
                    nuevo_logo,
                    telefono,
                    whatsapp,
                    email,
                    direccion,
                    moneda,
                    prefijo_pedido,
                    porcentaje_anticipo,
                    dias_vigencia_cotizacion,
                    banco,
                    tipo_cuenta,
                    numero_cuenta,
                    titular_cuenta,
                    notas_pago,
                    porcentaje_propietario,
                    porcentaje_reinversion,
                    porcentaje_reserva,
                    configuracion["id"]
                ))


            # =================================================
            # CREAR CONFIGURACIÓN SI NO EXISTE
            # =================================================

            else:

                cursor.execute("""
                    INSERT INTO configuracion_negocio (
                        nombre_negocio,
                        logo,
                        telefono,
                        whatsapp,
                        email,
                        direccion,
                        moneda,
                        prefijo_pedido,
                        porcentaje_anticipo,
                        dias_vigencia_cotizacion,
                        banco,
                        tipo_cuenta,
                        numero_cuenta,
                        titular_cuenta,
                        notas_pago,
                        porcentaje_propietario,
                        porcentaje_reinversion,
                        porcentaje_reserva
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                """, (
                    nombre_negocio,
                    nuevo_logo,
                    telefono,
                    whatsapp,
                    email,
                    direccion,
                    moneda,
                    prefijo_pedido,
                    porcentaje_anticipo,
                    dias_vigencia_cotizacion,
                    banco,
                    tipo_cuenta,
                    numero_cuenta,
                    titular_cuenta,
                    notas_pago,
                    porcentaje_propietario,
                    porcentaje_reinversion,
                    porcentaje_reserva
                ))


            conexion.commit()


            flash(
                "Configuración guardada correctamente.",
                "success"
            )


            return redirect(
                url_for(
                    "configuracion.index"
                )
            )


        # ====================================================
        # MOSTRAR CONFIGURACIÓN
        # ====================================================

        return render_template(
            "configuracion/index.html",
            configuracion=configuracion
        )


    except Exception as e:

        conexion.rollback()


        flash(
            f"No se pudo guardar la configuración: {e}",
            "danger"
        )


        cursor.execute("""
            SELECT *
            FROM configuracion_negocio
            ORDER BY id ASC
            LIMIT 1
        """)

        configuracion = cursor.fetchone()


        return render_template(
            "configuracion/index.html",
            configuracion=configuracion
        )


    finally:

        cursor.close()
        conexion.close()