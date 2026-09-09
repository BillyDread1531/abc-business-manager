from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import obtener_conexion
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
import calendar


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

    try:

        hoy = date.today()

        # ========================================================
        # CONFIGURACIÓN DE UTILIDADES
        # ========================================================

        cursor.execute("""
            SELECT
                porcentaje_propietario,
                porcentaje_reinversion,
                porcentaje_reserva
            FROM configuracion_negocio
            ORDER BY id ASC
            LIMIT 1
        """)

        configuracion = cursor.fetchone() or {}

        porcentaje_propietario = Decimal(
            str(configuracion.get("porcentaje_propietario", 50) or 50)
        )
        porcentaje_reinversion = Decimal(
            str(configuracion.get("porcentaje_reinversion", 30) or 30)
        )
        porcentaje_reserva = Decimal(
            str(configuracion.get("porcentaje_reserva", 20) or 20)
        )

        # ========================================================
        # TU GANANCIA: SEMANA / MES
        #
        # Solo cuenta pedidos:
        # 1) totalmente pagados
        # 2) con costo real completo
        #
        # venta - costo = ganancia
        # la ganancia positiva se reparte 50/30/20
        # ========================================================

        periodo_utilidad = request.args.get(
            "periodo_utilidad",
            "SEMANA"
        ).strip().upper()

        if periodo_utilidad not in {"SEMANA", "MES"}:
            periodo_utilidad = "SEMANA"

        if periodo_utilidad == "MES":
            utilidad_desde = hoy.replace(day=1)
        else:
            utilidad_desde = hoy - timedelta(days=hoy.weekday())

        utilidad_hasta = hoy

        etiqueta_periodo_utilidad = (
            utilidad_desde.strftime("%d/%m/%Y")
            + " - "
            + utilidad_hasta.strftime("%d/%m/%Y")
        )

        cursor.execute("""
            SELECT
                p.id,
                p.numero,
                p.total,

                pagos.total_pagado,
                pagos.fecha_ultimo_pago,

                costos.costo_real_total,
                costos.cantidad_detalles,
                costos.detalles_con_costo_real

            FROM pedidos p

            INNER JOIN (
                SELECT
                    pedido_id,
                    SUM(monto) AS total_pagado,
                    MAX(fecha) AS fecha_ultimo_pago
                FROM pagos
                GROUP BY pedido_id
            ) pagos
                ON pagos.pedido_id = p.id

            INNER JOIN (
                SELECT
                    pedido_id,
                    COUNT(*) AS cantidad_detalles,
                    SUM(
                        CASE
                            WHEN costo_real IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS detalles_con_costo_real,
                    SUM(COALESCE(costo_real, 0)) AS costo_real_total
                FROM detalle_pedido
                GROUP BY pedido_id
            ) costos
                ON costos.pedido_id = p.id

            WHERE p.estado != 'CANCELADO'
              AND pagos.total_pagado >= p.total
              AND costos.cantidad_detalles > 0
              AND costos.detalles_con_costo_real = costos.cantidad_detalles
              AND DATE(pagos.fecha_ultimo_pago) BETWEEN %s AND %s

            ORDER BY pagos.fecha_ultimo_pago DESC, p.id DESC
        """, (
            utilidad_desde,
            utilidad_hasta
        ))

        pedidos_ganancia = cursor.fetchall()

        ventas_confirmadas = Decimal("0.00")
        costos_confirmados = Decimal("0.00")
        utilidad_real = Decimal("0.00")
        ganancia_propietario = Decimal("0.00")
        monto_reinversion = Decimal("0.00")
        monto_reserva = Decimal("0.00")

        for item in pedidos_ganancia:

            venta = Decimal(
                str(item["total"] or 0)
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            costo = Decimal(
                str(item["costo_real_total"] or 0)
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            ganancia = (
                venta - costo
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            distribuible = max(
                ganancia,
                Decimal("0.00")
            )

            para_ti = (
                distribuible
                * porcentaje_propietario
                / Decimal("100")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            reinversion = (
                distribuible
                * porcentaje_reinversion
                / Decimal("100")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            reserva = (
                distribuible
                - para_ti
                - reinversion
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            item["venta"] = venta
            item["costo"] = costo
            item["ganancia"] = ganancia
            item["para_ti"] = para_ti
            item["reinversion"] = reinversion
            item["reserva"] = reserva

            ventas_confirmadas += venta
            costos_confirmados += costo
            utilidad_real += ganancia
            ganancia_propietario += para_ti
            monto_reinversion += reinversion
            monto_reserva += reserva

        ventas_confirmadas = ventas_confirmadas.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        costos_confirmados = costos_confirmados.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        utilidad_real = utilidad_real.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        ganancia_propietario = ganancia_propietario.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        monto_reinversion = monto_reinversion.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
        monto_reserva = monto_reserva.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # Pedidos con algún pago pero que todavía no están listos
        # para considerar ganancia personal.
        cursor.execute("""
            SELECT COUNT(*) AS cantidad
            FROM pedidos p

            LEFT JOIN (
                SELECT
                    pedido_id,
                    SUM(monto) AS total_pagado
                FROM pagos
                GROUP BY pedido_id
            ) pagos
                ON pagos.pedido_id = p.id

            LEFT JOIN (
                SELECT
                    pedido_id,
                    COUNT(*) AS cantidad_detalles,
                    SUM(
                        CASE
                            WHEN costo_real IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS detalles_con_costo_real
                FROM detalle_pedido
                GROUP BY pedido_id
            ) costos
                ON costos.pedido_id = p.id

            WHERE p.estado != 'CANCELADO'
              AND COALESCE(pagos.total_pagado, 0) > 0
              AND (
                    COALESCE(pagos.total_pagado, 0) < p.total
                    OR COALESCE(costos.cantidad_detalles, 0) = 0
                    OR COALESCE(costos.detalles_con_costo_real, 0)
                       < COALESCE(costos.cantidad_detalles, 0)
              )
        """)

        pedidos_pendientes_ganancia = int(
            cursor.fetchone()["cantidad"] or 0
        )

        # ========================================================
        # CAJA REAL DE ABC - ACUMULADO HISTÓRICO
        #
        # Esta parte NO se reinicia cada semana ni cada mes.
        #
        # Efectivo neto registrado:
        #   todos los ingresos - todos los egresos
        #
        # Caja de ABC:
        #   efectivo neto - tu 50% de ganancias confirmadas
        #
        # Para tu 50% solo se cuentan pedidos:
        #   - totalmente pagados
        #   - con costo real completo
        #
        # La reserva se protege primero. El resto de la caja
        # queda disponible para trabajar, comprar materiales,
        # empaques, reponer pérdidas, pagar proveedores, etc.
        # ========================================================

        cursor.execute("""
            SELECT
                COALESCE(SUM(monto), 0) AS total
            FROM ingresos
        """)

        ingresos_historicos = Decimal(
            str(cursor.fetchone()["total"] or 0)
        )

        cursor.execute("""
            SELECT
                COALESCE(SUM(monto), 0) AS total
            FROM egresos
        """)

        egresos_historicos = Decimal(
            str(cursor.fetchone()["total"] or 0)
        )

        efectivo_neto_registrado = (
            ingresos_historicos
            - egresos_historicos
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # --------------------------------------------------------
        # Ganancias confirmadas históricas de pedidos pagados
        # --------------------------------------------------------

        cursor.execute("""
            SELECT
                p.id,
                p.total,
                costos.costo_real_total

            FROM pedidos p

            INNER JOIN (
                SELECT
                    pedido_id,
                    SUM(monto) AS total_pagado
                FROM pagos
                GROUP BY pedido_id
            ) pagos
                ON pagos.pedido_id = p.id

            INNER JOIN (
                SELECT
                    pedido_id,
                    COUNT(*) AS cantidad_detalles,
                    SUM(
                        CASE
                            WHEN costo_real IS NOT NULL
                            THEN 1
                            ELSE 0
                        END
                    ) AS detalles_con_costo_real,
                    SUM(
                        COALESCE(costo_real, 0)
                    ) AS costo_real_total
                FROM detalle_pedido
                GROUP BY pedido_id
            ) costos
                ON costos.pedido_id = p.id

            WHERE p.estado != 'CANCELADO'
              AND pagos.total_pagado >= p.total
              AND costos.cantidad_detalles > 0
              AND costos.detalles_con_costo_real
                  = costos.cantidad_detalles
        """)

        pedidos_confirmados_historicos = cursor.fetchall()

        tu_dinero_historico = Decimal("0.00")
        reinversion_generada_historica = Decimal("0.00")
        reserva_generada_historica = Decimal("0.00")

        for item_historico in pedidos_confirmados_historicos:

            venta_historica = Decimal(
                str(item_historico["total"] or 0)
            )

            costo_historico = Decimal(
                str(
                    item_historico["costo_real_total"]
                    or 0
                )
            )

            ganancia_historica = (
                venta_historica
                - costo_historico
            )

            distribuible_historica = max(
                ganancia_historica,
                Decimal("0.00")
            )

            para_ti_historico = (
                distribuible_historica
                * porcentaje_propietario
                / Decimal("100")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            reinversion_historica = (
                distribuible_historica
                * porcentaje_reinversion
                / Decimal("100")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            reserva_historica = (
                distribuible_historica
                - para_ti_historico
                - reinversion_historica
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            tu_dinero_historico += para_ti_historico
            reinversion_generada_historica += reinversion_historica
            reserva_generada_historica += reserva_historica

        tu_dinero_historico = tu_dinero_historico.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        reinversion_generada_historica = (
            reinversion_generada_historica
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        reserva_generada_historica = (
            reserva_generada_historica
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # --------------------------------------------------------
        # Dinero que realmente sigue perteneciendo a ABC
        # --------------------------------------------------------

        caja_abc_actual = (
            efectivo_neto_registrado
            - tu_dinero_historico
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # La reserva se considera protegida dentro de la caja.
        # Si por algún motivo la caja real es menor que la reserva
        # generada, nunca mostramos más reserva disponible que
        # efectivo real de ABC.
        caja_abc_positiva = max(
            caja_abc_actual,
            Decimal("0.00")
        )

        reserva_disponible = min(
            reserva_generada_historica,
            caja_abc_positiva
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        disponible_para_trabajar = (
            caja_abc_actual
            - reserva_disponible
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # ========================================================
        # MOVIMIENTOS: MES / AÑO
        #
        # Por defecto abre el mes actual.
        # Esto es flujo de dinero, NO ganancia personal.
        # ========================================================

        try:
            mes_filtro = int(
                request.args.get("mes", hoy.month)
            )
        except (TypeError, ValueError):
            mes_filtro = hoy.month

        if mes_filtro < 1 or mes_filtro > 12:
            mes_filtro = hoy.month

        try:
            anio_filtro = int(
                request.args.get("anio", hoy.year)
            )
        except (TypeError, ValueError):
            anio_filtro = hoy.year

        if anio_filtro < 2000 or anio_filtro > 2100:
            anio_filtro = hoy.year

        tipo = request.args.get(
            "tipo",
            ""
        ).strip().upper()

        if tipo not in ("", "INGRESO", "EGRESO"):
            tipo = ""

        ultimo_dia = calendar.monthrange(
            anio_filtro,
            mes_filtro
        )[1]

        fecha_desde_obj = date(
            anio_filtro,
            mes_filtro,
            1
        )

        fecha_hasta_obj = date(
            anio_filtro,
            mes_filtro,
            ultimo_dia
        )

        fecha_desde = fecha_desde_obj.isoformat()
        fecha_hasta = fecha_hasta_obj.isoformat()

        nombres_meses = [
            "",
            "Enero",
            "Febrero",
            "Marzo",
            "Abril",
            "Mayo",
            "Junio",
            "Julio",
            "Agosto",
            "Septiembre",
            "Octubre",
            "Noviembre",
            "Diciembre"
        ]

        etiqueta_mes = (
            f"{nombres_meses[mes_filtro]} {anio_filtro}"
        )

        cursor.execute("""
            SELECT
                MIN(anio) AS minimo,
                MAX(anio) AS maximo
            FROM (
                SELECT YEAR(fecha) AS anio
                FROM ingresos

                UNION ALL

                SELECT YEAR(fecha) AS anio
                FROM egresos
            ) fechas
            WHERE anio IS NOT NULL
        """)

        rango_anios = cursor.fetchone() or {}

        anio_minimo = int(
            rango_anios.get("minimo") or hoy.year
        )
        anio_maximo = max(
            int(rango_anios.get("maximo") or hoy.year),
            hoy.year
        )

        anios_disponibles = list(
            range(
                anio_maximo,
                anio_minimo - 1,
                -1
            )
        )

        # --------------------------------------------------------
        # Totales del mes
        # --------------------------------------------------------

        cursor.execute("""
            SELECT COALESCE(SUM(monto), 0) AS total
            FROM ingresos
            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (
            fecha_desde,
            fecha_hasta
        ))

        total_ingresos = Decimal(
            str(cursor.fetchone()["total"] or 0)
        )

        cursor.execute("""
            SELECT COALESCE(SUM(monto), 0) AS total
            FROM egresos
            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (
            fecha_desde,
            fecha_hasta
        ))

        total_egresos = Decimal(
            str(cursor.fetchone()["total"] or 0)
        )

        cursor.execute("""
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN UPPER(categoria) = 'VENTA'
                            THEN monto
                            ELSE 0
                        END
                    ),
                    0
                ) AS ventas_cobradas,

                COALESCE(
                    SUM(
                        CASE
                            WHEN UPPER(categoria) != 'VENTA'
                            THEN monto
                            ELSE 0
                        END
                    ),
                    0
                ) AS otros_ingresos

            FROM ingresos

            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (
            fecha_desde,
            fecha_hasta
        ))

        resumen_ingresos = cursor.fetchone()

        ventas_cobradas = Decimal(
            str(resumen_ingresos["ventas_cobradas"] or 0)
        )
        otros_ingresos = Decimal(
            str(resumen_ingresos["otros_ingresos"] or 0)
        )

        cursor.execute("""
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN UPPER(categoria) = 'COMPRA'
                            THEN monto
                            ELSE 0
                        END
                    ),
                    0
                ) AS compras_pagadas,

                COALESCE(
                    SUM(
                        CASE
                            WHEN UPPER(categoria) != 'COMPRA'
                            THEN monto
                            ELSE 0
                        END
                    ),
                    0
                ) AS otros_egresos

            FROM egresos

            WHERE DATE(fecha) BETWEEN %s AND %s
        """, (
            fecha_desde,
            fecha_hasta
        ))

        resumen_egresos = cursor.fetchone()

        compras_pagadas = Decimal(
            str(resumen_egresos["compras_pagadas"] or 0)
        )
        otros_egresos = Decimal(
            str(resumen_egresos["otros_egresos"] or 0)
        )

        resultado = (
            total_ingresos - total_egresos
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # --------------------------------------------------------
        # Historial del mes
        # --------------------------------------------------------

        consultas = []
        parametros = []

        if tipo in ("", "INGRESO"):

            consultas.append("""
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
                WHERE DATE(i.fecha) BETWEEN %s AND %s
            """)

            parametros.extend([
                fecha_desde,
                fecha_hasta
            ])

        if tipo in ("", "EGRESO"):

            consultas.append("""
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
                WHERE DATE(e.fecha) BETWEEN %s AND %s
            """)

            parametros.extend([
                fecha_desde,
                fecha_hasta
            ])

        sql_movimientos = (
            " UNION ALL ".join(consultas)
            + " ORDER BY fecha DESC, id DESC"
        )

        cursor.execute(
            sql_movimientos,
            tuple(parametros)
        )

        movimientos = cursor.fetchall()

        return render_template(
            "finanzas/index.html",

            periodo_utilidad=periodo_utilidad,
            utilidad_desde=utilidad_desde,
            utilidad_hasta=utilidad_hasta,
            etiqueta_periodo_utilidad=etiqueta_periodo_utilidad,

            pedidos_ganancia=pedidos_ganancia,
            pedidos_pendientes_ganancia=pedidos_pendientes_ganancia,

            ventas_confirmadas=ventas_confirmadas,
            costos_confirmados=costos_confirmados,
            utilidad_real=utilidad_real,

            porcentaje_propietario=porcentaje_propietario,
            porcentaje_reinversion=porcentaje_reinversion,
            porcentaje_reserva=porcentaje_reserva,

            ganancia_propietario=ganancia_propietario,
            monto_reinversion=monto_reinversion,
            monto_reserva=monto_reserva,

            # Caja real del negocio
            ingresos_historicos=ingresos_historicos,
            egresos_historicos=egresos_historicos,
            efectivo_neto_registrado=efectivo_neto_registrado,
            tu_dinero_historico=tu_dinero_historico,
            reinversion_generada_historica=reinversion_generada_historica,
            reserva_generada_historica=reserva_generada_historica,
            caja_abc_actual=caja_abc_actual,
            reserva_disponible=reserva_disponible,
            disponible_para_trabajar=disponible_para_trabajar,

            mes_filtro=mes_filtro,
            anio_filtro=anio_filtro,
            anios_disponibles=anios_disponibles,
            nombres_meses=nombres_meses,
            etiqueta_mes=etiqueta_mes,

            total_ingresos=total_ingresos,
            total_egresos=total_egresos,
            resultado=resultado,

            ventas_cobradas=ventas_cobradas,
            otros_ingresos=otros_ingresos,
            compras_pagadas=compras_pagadas,
            otros_egresos=otros_egresos,

            movimientos=movimientos,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            tipo_filtro=tipo
        )

    finally:

        cursor.close()
        conn.close()


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