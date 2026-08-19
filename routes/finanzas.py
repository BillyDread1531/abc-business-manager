from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import obtener_conexion
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta


finanzas_bp = Blueprint(
    "finanzas",
    __name__,
    url_prefix="/finanzas"
)


# ============================================================
# PANEL PRINCIPAL
# ============================================================

@finanzas_bp.route("/")
def index():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    # --------------------------------------------------------
    # UTILIDAD DISTRIBUIBLE: SEMANA / MES
    # --------------------------------------------------------

    periodo_utilidad = request.args.get(
        "periodo_utilidad",
        "SEMANA"
    ).strip().upper()

    if periodo_utilidad not in {
        "SEMANA",
        "MES"
    }:
        periodo_utilidad = "SEMANA"

    hoy = date.today()

    if periodo_utilidad == "MES":

        utilidad_desde = hoy.replace(
            day=1
        )

        utilidad_hasta = hoy

        etiqueta_periodo_utilidad = (
            utilidad_desde.strftime("%d/%m/%Y")
            + " - "
            + utilidad_hasta.strftime("%d/%m/%Y")
        )

    else:

        utilidad_desde = (
            hoy
            - timedelta(
                days=hoy.weekday()
            )
        )

        utilidad_hasta = hoy

        etiqueta_periodo_utilidad = (
            utilidad_desde.strftime("%d/%m/%Y")
            + " - "
            + utilidad_hasta.strftime("%d/%m/%Y")
        )

    # Configuración de distribución.
    cursor.execute("""
        SELECT
            porcentaje_propietario,
            porcentaje_reinversion,
            porcentaje_reserva
        FROM configuracion_negocio
        ORDER BY id ASC
        LIMIT 1
    """)

    configuracion_utilidad = (
        cursor.fetchone()
        or {}
    )

    porcentaje_propietario = Decimal(
        str(
            configuracion_utilidad.get(
                "porcentaje_propietario",
                50
            )
            or 50
        )
    )

    porcentaje_reinversion = Decimal(
        str(
            configuracion_utilidad.get(
                "porcentaje_reinversion",
                30
            )
            or 30
        )
    )

    porcentaje_reserva = Decimal(
        str(
            configuracion_utilidad.get(
                "porcentaje_reserva",
                20
            )
            or 20
        )
    )

    # Ventas realmente cobradas durante el período.
    cursor.execute("""
        SELECT
            COALESCE(SUM(i.monto), 0) AS total
        FROM ingresos i
        WHERE UPPER(i.categoria) = 'VENTA'
          AND DATE(i.fecha) BETWEEN %s AND %s
    """, (
        utilidad_desde,
        utilidad_hasta
    ))

    ventas_cobradas_utilidad = Decimal(
        str(
            cursor.fetchone()["total"]
            or 0
        )
    )

    # Otros ingresos se muestran como referencia, pero NO se
    # distribuyen automáticamente. Así una aportación de capital,
    # devolución u otro ingreso manual no se confunde con utilidad
    # generada por ventas.
    cursor.execute("""
        SELECT
            COALESCE(SUM(i.monto), 0) AS total
        FROM ingresos i
        WHERE UPPER(i.categoria) != 'VENTA'
          AND DATE(i.fecha) BETWEEN %s AND %s
    """, (
        utilidad_desde,
        utilidad_hasta
    ))

    otros_ingresos_utilidad = Decimal(
        str(
            cursor.fetchone()["total"]
            or 0
        )
    )

    # Gastos operativos del período.
    #
    # Las compras de inventario NO se restan aquí otra vez porque
    # su costo se reconoce cuando el material se consume en una venta.
    cursor.execute("""
        SELECT
            COALESCE(SUM(e.monto), 0) AS total
        FROM egresos e
        WHERE UPPER(e.categoria) != 'COMPRA'
          AND DATE(e.fecha) BETWEEN %s AND %s
    """, (
        utilidad_desde,
        utilidad_hasta
    ))

    gastos_operativos_utilidad = Decimal(
        str(
            cursor.fetchone()["total"]
            or 0
        )
    )

    # --------------------------------------------------------
    # COSTO ASOCIADO A LAS VENTAS COBRADAS
    #
    # Si un pedido se paga parcialmente, solo se reconoce la
    # misma proporción de su costo. Esto evita cargar todo el
    # costo a una semana cuando solo se cobró un anticipo.
    #
    # Prioridad de costo por detalle:
    # 1. costo real del detalle
    # 2. costo real de producción
    # 3. costo estimado de producción
    # 4. costo estimado del detalle
    # --------------------------------------------------------

    cursor.execute("""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN p.total > 0
                        THEN
                            LEAST(
                                cobros.cobrado_periodo / p.total,
                                1
                            )
                            * COALESCE(costos.costo_pedido, 0)
                        ELSE 0
                    END
                ),
                0
            ) AS costo_asociado

        FROM (
            SELECT
                i.pedido_id,
                SUM(i.monto) AS cobrado_periodo
            FROM ingresos i
            WHERE UPPER(i.categoria) = 'VENTA'
              AND i.pedido_id IS NOT NULL
              AND DATE(i.fecha) BETWEEN %s AND %s
            GROUP BY i.pedido_id
        ) cobros

        INNER JOIN pedidos p
            ON p.id = cobros.pedido_id

        LEFT JOIN (
            SELECT
                dp.pedido_id,
                SUM(
                    COALESCE(
                        dp.costo_real,
                        pr.costo_real,
                        NULLIF(pr.costo_estimado, 0),
                        NULLIF(dp.costo_estimado, 0),
                        0
                    )
                ) AS costo_pedido
            FROM detalle_pedido dp

            LEFT JOIN producciones pr
                ON pr.detalle_pedido_id = dp.id
               AND pr.estado != 'CANCELADO'

            GROUP BY dp.pedido_id
        ) costos
            ON costos.pedido_id = p.id

        WHERE p.estado != 'CANCELADO'
    """, (
        utilidad_desde,
        utilidad_hasta
    ))

    costo_ventas_utilidad = Decimal(
        str(
            cursor.fetchone()["costo_asociado"]
            or 0
        )
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    utilidad_real = (
        ventas_cobradas_utilidad
        - costo_ventas_utilidad
        - gastos_operativos_utilidad
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    utilidad_distribuible = max(
        utilidad_real,
        Decimal("0.00")
    )

    ganancia_propietario = (
        utilidad_distribuible
        * porcentaje_propietario
        / Decimal("100")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    monto_reinversion = (
        utilidad_distribuible
        * porcentaje_reinversion
        / Decimal("100")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    monto_reserva = (
        utilidad_distribuible
        - ganancia_propietario
        - monto_reinversion
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    # --------------------------------------------------------
    # FILTROS
    # --------------------------------------------------------

    fecha_desde = request.args.get("desde", "").strip()
    fecha_hasta = request.args.get("hasta", "").strip()
    tipo = request.args.get("tipo", "").strip().upper()

    if tipo not in ("", "INGRESO", "EGRESO"):
        tipo = ""

    # --------------------------------------------------------
    # Construir filtros
    # --------------------------------------------------------

    condiciones_ingresos = []
    parametros_ingresos = []

    condiciones_egresos = []
    parametros_egresos = []

    if fecha_desde:

        condiciones_ingresos.append(
            "DATE(i.fecha) >= %s"
        )

        parametros_ingresos.append(
            fecha_desde
        )

        condiciones_egresos.append(
            "DATE(e.fecha) >= %s"
        )

        parametros_egresos.append(
            fecha_desde
        )

    if fecha_hasta:

        condiciones_ingresos.append(
            "DATE(i.fecha) <= %s"
        )

        parametros_ingresos.append(
            fecha_hasta
        )

        condiciones_egresos.append(
            "DATE(e.fecha) <= %s"
        )

        parametros_egresos.append(
            fecha_hasta
        )


    where_ingresos = ""

    if condiciones_ingresos:

        where_ingresos = (
            "WHERE "
            + " AND ".join(condiciones_ingresos)
        )


    where_egresos = ""

    if condiciones_egresos:

        where_egresos = (
            "WHERE "
            + " AND ".join(condiciones_egresos)
        )


    # --------------------------------------------------------
    # TOTAL INGRESOS
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(i.monto), 0) AS total
        FROM ingresos i
        {where_ingresos}
        """,
        tuple(parametros_ingresos)
    )

    total_ingresos = cursor.fetchone()["total"]


    # --------------------------------------------------------
    # TOTAL EGRESOS
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(e.monto), 0) AS total
        FROM egresos e
        {where_egresos}
        """,
        tuple(parametros_egresos)
    )

    total_egresos = cursor.fetchone()["total"]


    # --------------------------------------------------------
    # DESGLOSE DE INGRESOS
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN i.categoria = 'VENTA'
                        THEN i.monto
                        ELSE 0
                    END
                ),
                0
            ) AS ventas_cobradas,

            COALESCE(
                SUM(
                    CASE
                        WHEN i.categoria != 'VENTA'
                        THEN i.monto
                        ELSE 0
                    END
                ),
                0
            ) AS otros_ingresos

        FROM ingresos i

        {where_ingresos}
        """,
        tuple(parametros_ingresos)
    )

    resumen_ingresos = cursor.fetchone()

    ventas_cobradas = resumen_ingresos["ventas_cobradas"]
    otros_ingresos = resumen_ingresos["otros_ingresos"]


    # --------------------------------------------------------
    # DESGLOSE DE EGRESOS
    # --------------------------------------------------------

    cursor.execute(
        f"""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN e.categoria = 'COMPRA'
                        THEN e.monto
                        ELSE 0
                    END
                ),
                0
            ) AS compras_pagadas,

            COALESCE(
                SUM(
                    CASE
                        WHEN e.categoria != 'COMPRA'
                        THEN e.monto
                        ELSE 0
                    END
                ),
                0
            ) AS otros_egresos

        FROM egresos e

        {where_egresos}
        """,
        tuple(parametros_egresos)
    )

    resumen_egresos = cursor.fetchone()

    compras_pagadas = resumen_egresos["compras_pagadas"]
    otros_egresos = resumen_egresos["otros_egresos"]

    # --------------------------------------------------------
    # MOVIMIENTOS
    # --------------------------------------------------------

    consultas = []
    parametros_movimientos = []


    if tipo in ("", "INGRESO"):

        consultas.append(
            f"""
            SELECT
                i.id,
                i.fecha,
                'INGRESO' AS tipo,
                i.categoria,
                i.descripcion,
                i.monto,

                i.pedido_id,
                NULL AS compra_id,

                p.numero AS pedido_numero,
                NULL AS compra_numero

            FROM ingresos i

            LEFT JOIN pedidos p
                ON i.pedido_id = p.id

            {where_ingresos}
            """
        )

        parametros_movimientos.extend(
            parametros_ingresos
        )


    if tipo in ("", "EGRESO"):

        consultas.append(
            f"""
            SELECT
                e.id,
                e.fecha,
                'EGRESO' AS tipo,
                e.categoria,
                e.descripcion,
                e.monto,

                e.pedido_id,
                e.compra_id,

                p.numero AS pedido_numero,
                c.numero AS compra_numero

            FROM egresos e

            LEFT JOIN pedidos p
                ON e.pedido_id = p.id

            LEFT JOIN compras c
                ON e.compra_id = c.id

            {where_egresos}
            """
        )

        parametros_movimientos.extend(
            parametros_egresos
        )


    sql_movimientos = (
        " UNION ALL ".join(consultas)
        + " ORDER BY fecha DESC, id DESC"
    )


    cursor.execute(
        sql_movimientos,
        tuple(parametros_movimientos)
    )

    movimientos = cursor.fetchall()


    # --------------------------------------------------------
    # Resultado
    # --------------------------------------------------------

    resultado = (
        Decimal(str(total_ingresos))
        - Decimal(str(total_egresos))
    )


    cursor.close()
    conn.close()


    return render_template(
        "finanzas/index.html",
        total_ingresos=total_ingresos,
        total_egresos=total_egresos,
        resultado=resultado,
        movimientos=movimientos,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo_filtro=tipo,
        ventas_cobradas=ventas_cobradas,
        otros_ingresos=otros_ingresos,
        compras_pagadas=compras_pagadas,
        otros_egresos=otros_egresos,

        periodo_utilidad=periodo_utilidad,
        utilidad_desde=utilidad_desde,
        utilidad_hasta=utilidad_hasta,
        etiqueta_periodo_utilidad=etiqueta_periodo_utilidad,

        ventas_cobradas_utilidad=ventas_cobradas_utilidad,
        otros_ingresos_utilidad=otros_ingresos_utilidad,
        costo_ventas_utilidad=costo_ventas_utilidad,
        gastos_operativos_utilidad=gastos_operativos_utilidad,
        utilidad_real=utilidad_real,
        utilidad_distribuible=utilidad_distribuible,

        porcentaje_propietario=porcentaje_propietario,
        porcentaje_reinversion=porcentaje_reinversion,
        porcentaje_reserva=porcentaje_reserva,

        ganancia_propietario=ganancia_propietario,
        monto_reinversion=monto_reinversion,
        monto_reserva=monto_reserva,
    )


# ============================================================
# NUEVO INGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/ingresos/nuevo",
    methods=["GET", "POST"]
)
def nuevo_ingreso():

    if request.method == "POST":

        conn = obtener_conexion()
        cursor = conn.cursor()

        try:

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get(
                "fecha"
            ) or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None


            if monto <= 0:

                raise ValueError(
                    "El monto debe ser mayor que cero."
                )


            if not categoria:

                raise ValueError(
                    "La categoría es obligatoria."
                )


            cursor.execute("""
                INSERT INTO ingresos (
                    pedido_id,
                    pago_id,
                    usuario_id,
                    categoria,
                    monto,
                    fecha,
                    descripcion
                )
                VALUES (
                    NULL,
                    NULL,
                    %s,
                    %s,
                    %s,
                    COALESCE(%s, NOW()),
                    %s
                )
            """, (
                8,
                categoria,
                monto,
                fecha,
                descripcion
            ))

            conn.commit()

            flash(
                "Ingreso registrado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )


        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo registrar el ingreso: {e}",
                "danger"
            )


        finally:

            cursor.close()
            conn.close()


    return render_template(
        "finanzas/nuevo_ingreso.html"
    )


# ============================================================
# NUEVO EGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/egresos/nuevo",
    methods=["GET", "POST"]
)
def nuevo_egreso():

    if request.method == "POST":

        conn = obtener_conexion()
        cursor = conn.cursor()

        try:

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get(
                "fecha"
            ) or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None


            if monto <= 0:

                raise ValueError(
                    "El monto debe ser mayor que cero."
                )


            if not categoria:

                raise ValueError(
                    "La categoría es obligatoria."
                )


            cursor.execute("""
                INSERT INTO egresos (
                    pedido_id,
                    proveedor_id,
                    compra_id,
                    usuario_id,
                    categoria,
                    monto,
                    fecha,
                    descripcion
                )
                VALUES (
                    NULL,
                    NULL,
                    NULL,
                    %s,
                    %s,
                    %s,
                    COALESCE(%s, NOW()),
                    %s
                )
            """, (
                8,
                categoria,
                monto,
                fecha,
                descripcion
            ))

            conn.commit()

            flash(
                "Egreso registrado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )


        except Exception as e:

            conn.rollback()

            flash(
                f"No se pudo registrar el egreso: {e}",
                "danger"
            )


        finally:

            cursor.close()
            conn.close()


    return render_template(
        "finanzas/nuevo_egreso.html"
    )

# ============================================================
# EDITAR INGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/ingresos/<int:ingreso_id>/editar",
    methods=["GET", "POST"]
)
def editar_ingreso(ingreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                pago_id,
                categoria,
                monto,
                fecha,
                descripcion
            FROM ingresos
            WHERE id = %s
        """, (ingreso_id,))

        ingreso = cursor.fetchone()

        if not ingreso:
            raise ValueError(
                "El ingreso no existe."
            )

        if ingreso["pedido_id"] is not None or ingreso["pago_id"] is not None:
            raise ValueError(
                "Este ingreso fue generado automáticamente "
                "y no puede editarse desde Finanzas."
            )

        if request.method == "POST":

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get("fecha") or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None

            if monto <= 0:
                raise ValueError(
                    "El monto debe ser mayor que cero."
                )

            if not categoria:
                raise ValueError(
                    "La categoría es obligatoria."
                )

            cursor.execute("""
                UPDATE ingresos
                SET
                    categoria = %s,
                    monto = %s,
                    fecha = COALESCE(%s, fecha),
                    descripcion = %s
                WHERE id = %s
            """, (
                categoria,
                monto,
                fecha,
                descripcion,
                ingreso_id
            ))

            conn.commit()

            flash(
                "Ingreso actualizado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )

        return render_template(
            "finanzas/editar_ingreso.html",
            ingreso=ingreso
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo editar el ingreso: {e}",
            "danger"
        )

        return redirect(
            url_for("finanzas.index")
        )

    finally:

        cursor.close()
        conn.close()


# ============================================================
# ELIMINAR INGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/ingresos/<int:ingreso_id>/eliminar",
    methods=["POST"]
)
def eliminar_ingreso(ingreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                pago_id
            FROM ingresos
            WHERE id = %s
        """, (ingreso_id,))

        ingreso = cursor.fetchone()

        if not ingreso:
            raise ValueError(
                "El ingreso no existe."
            )

        if ingreso["pedido_id"] is not None or ingreso["pago_id"] is not None:
            raise ValueError(
                "Este ingreso fue generado automáticamente "
                "y no puede eliminarse."
            )

        cursor.execute("""
            DELETE FROM ingresos
            WHERE id = %s
        """, (ingreso_id,))

        conn.commit()

        flash(
            "Ingreso eliminado correctamente.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo eliminar el ingreso: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for("finanzas.index")
    )


# ============================================================
# EDITAR EGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/egresos/<int:egreso_id>/editar",
    methods=["GET", "POST"]
)
def editar_egreso(egreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                proveedor_id,
                compra_id,
                categoria,
                monto,
                fecha,
                descripcion
            FROM egresos
            WHERE id = %s
        """, (egreso_id,))

        egreso = cursor.fetchone()

        if not egreso:
            raise ValueError(
                "El egreso no existe."
            )

        if egreso["compra_id"] is not None or egreso["pedido_id"] is not None:
            raise ValueError(
                "Este egreso fue generado automáticamente "
                "y no puede editarse desde Finanzas."
            )

        if request.method == "POST":

            monto = Decimal(
                request.form.get("monto", "0")
            )

            categoria = request.form.get(
                "categoria",
                ""
            ).strip().title()

            fecha = request.form.get("fecha") or None

            descripcion = request.form.get(
                "descripcion",
                ""
            ).strip() or None

            if monto <= 0:
                raise ValueError(
                    "El monto debe ser mayor que cero."
                )

            if not categoria:
                raise ValueError(
                    "La categoría es obligatoria."
                )

            cursor.execute("""
                UPDATE egresos
                SET
                    categoria = %s,
                    monto = %s,
                    fecha = COALESCE(%s, fecha),
                    descripcion = %s
                WHERE id = %s
            """, (
                categoria,
                monto,
                fecha,
                descripcion,
                egreso_id
            ))

            conn.commit()

            flash(
                "Egreso actualizado correctamente.",
                "success"
            )

            return redirect(
                url_for("finanzas.index")
            )

        return render_template(
            "finanzas/editar_egreso.html",
            egreso=egreso
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo editar el egreso: {e}",
            "danger"
        )

        return redirect(
            url_for("finanzas.index")
        )

    finally:

        cursor.close()
        conn.close()


# ============================================================
# ELIMINAR EGRESO MANUAL
# ============================================================

@finanzas_bp.route(
    "/egresos/<int:egreso_id>/eliminar",
    methods=["POST"]
)
def eliminar_egreso(egreso_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                id,
                pedido_id,
                compra_id
            FROM egresos
            WHERE id = %s
        """, (egreso_id,))

        egreso = cursor.fetchone()

        if not egreso:
            raise ValueError(
                "El egreso no existe."
            )

        if egreso["compra_id"] is not None or egreso["pedido_id"] is not None:
            raise ValueError(
                "Este egreso fue generado automáticamente "
                "y no puede eliminarse."
            )

        cursor.execute("""
            DELETE FROM egresos
            WHERE id = %s
        """, (egreso_id,))

        conn.commit()

        flash(
            "Egreso eliminado correctamente.",
            "success"
        )

    except Exception as e:

        conn.rollback()

        flash(
            f"No se pudo eliminar el egreso: {e}",
            "danger"
        )

    finally:

        cursor.close()
        conn.close()

    return redirect(
        url_for("finanzas.index")
    )