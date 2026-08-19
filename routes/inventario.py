from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import obtener_conexion
from decimal import Decimal

inventario_bp = Blueprint(
    "inventario",
    __name__,
    url_prefix="/inventario"
)


# ==========================================================
# UTILIDADES DE PRESENTACIÓN
# ==========================================================

@inventario_bp.app_template_filter("numero_inventario")
def numero_inventario(valor):

    if valor is None:
        return "0"

    try:
        numero = Decimal(str(valor))
    except Exception:
        return str(valor)

    texto = f"{numero:.4f}".rstrip("0").rstrip(".")

    return texto if texto else "0"




# ==========================================================
# LISTA DE INVENTARIO
# ==========================================================

@inventario_bp.route("/")
def lista():

    busqueda = request.args.get(
        "q",
        ""
    ).strip()

    filtro = request.args.get(
        "filtro",
        "todos"
    ).strip().lower()

    filtros_validos = {
        "todos",
        "disponible",
        "bajo",
        "agotado"
    }

    if filtro not in filtros_validos:
        filtro = "todos"


    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)


    condiciones = [
        "m.activo = 1"
    ]

    parametros = []


    # ------------------------------------------------------
    # BUSCADOR
    # ------------------------------------------------------

    if busqueda:

        termino = f"%{busqueda}%"

        condiciones.append("""
            (
                m.nombre LIKE %s
                OR m.color LIKE %s
                OR c.nombre LIKE %s
            )
        """)

        parametros.extend([
            termino,
            termino,
            termino
        ])


    # ------------------------------------------------------
    # FILTROS
    # ------------------------------------------------------

    if filtro == "disponible":

        condiciones.append("""
            m.stock_actual > m.stock_minimo
        """)

    elif filtro == "bajo":

        condiciones.append("""
            m.stock_actual > 0
            AND m.stock_actual <= m.stock_minimo
        """)

    elif filtro == "agotado":

        condiciones.append("""
            m.stock_actual <= 0
        """)


    where_sql = (
        "WHERE "
        + " AND ".join(condiciones)
    )


    cursor.execute(
        f"""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.stock_actual,
            m.stock_minimo,
            m.costo_compra_referencia,

            um.nombre AS unidad,
            um.abreviatura,

            c.nombre AS categoria

        FROM materiales m

        LEFT JOIN unidades_medida um
            ON m.unidad_consumo_id = um.id

        LEFT JOIN categorias c
            ON m.categoria_id = c.id

        {where_sql}

        ORDER BY m.nombre ASC
        """,
        tuple(parametros)
    )


    materiales = cursor.fetchall()


    # ------------------------------------------------------
    # CONTADORES
    # ------------------------------------------------------

    cursor.execute("""
        SELECT

            COUNT(*) AS todos,

            SUM(
                CASE
                    WHEN stock_actual > stock_minimo
                    THEN 1
                    ELSE 0
                END
            ) AS disponibles,

            SUM(
                CASE
                    WHEN stock_actual > 0
                     AND stock_actual <= stock_minimo
                    THEN 1
                    ELSE 0
                END
            ) AS bajos,

            SUM(
                CASE
                    WHEN stock_actual <= 0
                    THEN 1
                    ELSE 0
                END
            ) AS agotados

        FROM materiales

        WHERE activo = 1
    """)

    contadores = cursor.fetchone()


    cursor.close()
    conn.close()


    return render_template(
        "inventario/lista.html",

        materiales=materiales,

        busqueda=busqueda,
        filtro=filtro,

        contadores=contadores
    )


# ==========================================================
# ENTRADA DE INVENTARIO
# ==========================================================
@inventario_bp.route("/entrada", methods=["GET", "POST"])
def entrada():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        material_id = request.form.get("material_id")
        cantidad = request.form.get("cantidad")
        costo_unitario = request.form.get("costo_unitario")
        notas = request.form.get("notas", "").strip()

        if not material_id or not cantidad:
            flash(
                "Debes seleccionar un material e indicar la cantidad.",
                "danger"
            )

        else:

            try:

                cantidad = float(cantidad)
                costo_unitario = float(costo_unitario or 0)

                if cantidad <= 0:
                    raise ValueError(
                        "La cantidad debe ser mayor que cero."
                    )

                if costo_unitario < 0:
                    raise ValueError(
                        "El costo no puede ser negativo."
                    )

                # ==========================================
                # OBTENER INFORMACIÓN DEL MATERIAL
                # ==========================================

                cursor.execute("""
                    SELECT
                        m.id,
                        m.nombre,
                        m.unidad_compra_id,
                        m.unidad_consumo_id,
                        m.cantidad_por_compra,
                        m.stock_actual,

                        uc.nombre AS unidad_compra,
                        uc.abreviatura AS abreviatura_compra,
                        uc.tipo AS tipo_compra,

                        ucons.nombre AS unidad_consumo,
                        ucons.abreviatura AS abreviatura_consumo,
                        ucons.tipo AS tipo_consumo

                    FROM materiales m

                    INNER JOIN unidades_medida uc
                        ON m.unidad_compra_id = uc.id

                    INNER JOIN unidades_medida ucons
                        ON m.unidad_consumo_id = ucons.id

                    WHERE m.id = %s
                      AND m.activo = 1
                """, (material_id,))

                material = cursor.fetchone()

                if not material:
                    raise ValueError(
                        "El material seleccionado no existe."
                    )

                # ==========================================
                # DATOS DEL MATERIAL
                # ==========================================

                unidad_compra = material["unidad_compra_id"]
                unidad_consumo = material["unidad_consumo_id"]

                tipo_compra = material["tipo_compra"]
                tipo_consumo = material["tipo_consumo"]

                cantidad_por_compra = float(
                    material["cantidad_por_compra"]
                )

                # ==========================================
                # CALCULAR COSTO TOTAL DE LA COMPRA
                #
                # Ejemplo:
                # 10 pies × Q8 = Q80
                # ==========================================

                costo_total_compra = (
                    cantidad * costo_unitario
                )

                # ==========================================
                # CONVERSIÓN DE UNIDADES
                # ==========================================

                # ------------------------------------------
                # MISMA UNIDAD
                # ------------------------------------------

                if unidad_compra == unidad_consumo:

                    cantidad_consumo = cantidad

                # ------------------------------------------
                # PIE -> CENTÍMETRO
                # ------------------------------------------

                elif unidad_compra == 4 and unidad_consumo == 2:

                    cantidad_consumo = cantidad * 30.48

                # ------------------------------------------
                # YARDA -> CENTÍMETRO
                # ------------------------------------------

                elif unidad_compra == 5 and unidad_consumo == 2:

                    cantidad_consumo = cantidad * 91.44

                # ------------------------------------------
                # METRO -> CENTÍMETRO
                # ------------------------------------------

                elif unidad_compra == 3 and unidad_consumo == 2:

                    cantidad_consumo = cantidad * 100

                # ------------------------------------------
                # PAQUETE -> HOJA
                #
                # Ejemplo:
                # 1 paquete × 100 = 100 hojas
                # ------------------------------------------

                elif unidad_compra == 9 and unidad_consumo == 8:

                    cantidad_consumo = (
                        cantidad * cantidad_por_compra
                    )

                # ------------------------------------------
                # CONVERSIÓN NO CONFIGURADA
                # ------------------------------------------

                else:

                    raise ValueError(
                        f"No existe una conversión configurada entre "
                        f"{material['unidad_compra']} y "
                        f"{material['unidad_consumo']}."
                    )

                # ==========================================
                # VALIDAR CANTIDAD CONVERTIDA
                # ==========================================

                if cantidad_consumo <= 0:
                    raise ValueError(
                        "La cantidad convertida debe ser mayor que cero."
                    )

                # ==========================================
                # CALCULAR COSTO POR UNIDAD DE CONSUMO
                #
                # Ejemplo:
                #
                # 10 pies × Q8 = Q80
                #
                # 10 pies = 304.80 cm
                #
                # Q80 / 304.80 = Q0.262467/cm
                # ==========================================

                costo_por_unidad_consumo = (
                    costo_total_compra / cantidad_consumo
                )

                # ==========================================
                # ACTUALIZAR STOCK
                # ==========================================

                cursor.execute("""
                    UPDATE materiales
                    SET
                        stock_actual = stock_actual + %s,
                        costo_compra_referencia = %s
                    WHERE id = %s
                """, (
                    cantidad_consumo,
                    costo_por_unidad_consumo,
                    material_id
                ))

                # ==========================================
                # REGISTRAR MOVIMIENTO
                # ==========================================

                cursor.execute("""
                    INSERT INTO movimientos_inventario (
                        material_id,
                        variante_id,
                        tipo,
                        cantidad,
                        unidad_id,
                        costo_unitario,
                        referencia_tipo,
                        referencia_id,
                        usuario_id,
                        notas
                    )
                    VALUES (
                        %s,
                        NULL,
                        'COMPRA',
                        %s,
                        %s,
                        %s,
                        'ENTRADA_MANUAL',
                        NULL,
                        %s,
                        %s
                    )
                """, (
                    material_id,
                    cantidad_consumo,
                    unidad_consumo,
                    costo_por_unidad_consumo,
                    8,
                    notas
                ))

                # ==========================================
                # CREAR LOTE
                # ==========================================

                cursor.execute("""
                    INSERT INTO lotes_inventario (
                        material_id,
                        variante_id,
                        compra_id,
                        detalle_compra_id,
                        cantidad_original,
                        cantidad_actual,
                        unidad_id,
                        ancho,
                        largo,
                        area_total,
                        area_disponible,
                        costo_total,
                        costo_unitario,
                        activo
                    )
                    VALUES (
                        %s,
                        NULL,
                        NULL,
                        NULL,
                        %s,
                        %s,
                        %s,
                        NULL,
                        NULL,
                        NULL,
                        NULL,
                        %s,
                        %s,
                        1
                    )
                """, (
                    material_id,
                    cantidad_consumo,
                    cantidad_consumo,
                    unidad_consumo,
                    costo_total_compra,
                    costo_por_unidad_consumo
                ))

                # ==========================================
                # GUARDAR TODO
                # ==========================================

                conn.commit()

                # ==========================================
                # MENSAJE DE CONFIRMACIÓN
                # ==========================================

                flash(
                    f"Entrada registrada: "
                    f"{cantidad:g} "
                    f"{material['abreviatura_compra']} → "
                    f"{cantidad_consumo:.4f} "
                    f"{material['abreviatura_consumo']}. "
                    f"Costo total: Q{costo_total_compra:.2f}. "
                    f"Costo por "
                    f"{material['abreviatura_consumo']}: "
                    f"Q{costo_por_unidad_consumo:.4f}.",
                    "success"
                )

                cursor.close()
                conn.close()

                return redirect(
                    url_for("inventario.lista")
                )

            except Exception as e:

                conn.rollback()

                flash(
                    f"No se pudo registrar la entrada: {e}",
                    "danger"
                )

    # ==========================================
    # MATERIALES DISPONIBLES
    # ==========================================

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.unidad_compra_id,
            m.unidad_consumo_id,
            m.cantidad_por_compra,

            uc.nombre AS unidad_compra,
            uc.abreviatura AS abreviatura_compra,

            ucons.nombre AS unidad_consumo,
            ucons.abreviatura AS abreviatura_consumo

        FROM materiales m

        INNER JOIN unidades_medida uc
            ON m.unidad_compra_id = uc.id

        INNER JOIN unidades_medida ucons
            ON m.unidad_consumo_id = ucons.id

        WHERE m.activo = 1

        ORDER BY m.nombre ASC
    """)

    materiales = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "inventario/entrada.html",
        materiales=materiales
    )



@inventario_bp.route("/salida", methods=["GET", "POST"])
def salida():

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        material_id = request.form.get("material_id")
        cantidad = request.form.get("cantidad")
        unidad_entrada = request.form.get("unidad_id")
        notas = request.form.get("notas", "").strip()

        if not material_id or not cantidad or not unidad_entrada:
            flash(
                "Debes seleccionar un material, indicar la cantidad y la unidad.",
                "danger"
            )

        else:

            try:

                cantidad = float(cantidad)
                unidad_entrada = int(unidad_entrada)

                if cantidad <= 0:
                    raise ValueError(
                        "La cantidad debe ser mayor que cero."
                    )

                # ======================================================
                # OBTENER MATERIAL
                # ======================================================

                cursor.execute("""
                    SELECT
                        m.id,
                        m.nombre,
                        m.color,
                        m.stock_actual,
                        m.unidad_compra_id,
                        m.unidad_consumo_id,
                        m.cantidad_por_compra,

                        uc.nombre AS unidad_compra,
                        uc.abreviatura AS abreviatura_compra,
                        uc.tipo AS tipo_compra,
                        uc.factor_conversion AS factor_compra,

                        ucons.nombre AS unidad_consumo,
                        ucons.abreviatura AS abreviatura_consumo,
                        ucons.tipo AS tipo_consumo,
                        ucons.factor_conversion AS factor_consumo

                    FROM materiales m

                    INNER JOIN unidades_medida uc
                        ON m.unidad_compra_id = uc.id

                    INNER JOIN unidades_medida ucons
                        ON m.unidad_consumo_id = ucons.id

                    WHERE m.id = %s
                      AND m.activo = 1
                """, (material_id,))

                material = cursor.fetchone()

                if not material:
                    raise ValueError(
                        "El material seleccionado no existe."
                    )

                # ======================================================
                # OBTENER UNIDAD UTILIZADA EN LA SALIDA
                # ======================================================

                cursor.execute("""
                    SELECT
                        id,
                        nombre,
                        abreviatura,
                        tipo,
                        factor_conversion
                    FROM unidades_medida
                    WHERE id = %s
                """, (unidad_entrada,))

                unidad = cursor.fetchone()

                if not unidad:
                    raise ValueError(
                        "La unidad seleccionada no existe."
                    )

                # ======================================================
                # DATOS
                # ======================================================

                unidad_consumo = material["unidad_consumo_id"]
                unidad_compra = material["unidad_compra_id"]

                tipo_consumo = material["tipo_consumo"]
                tipo_compra = material["tipo_compra"]

                tipo_entrada = unidad["tipo"]

                factor_consumo = float(
                    material["factor_consumo"] or 1
                )

                factor_entrada = float(
                    unidad["factor_conversion"] or 1
                )

                cantidad_por_compra = float(
                    material["cantidad_por_compra"] or 1
                )

                # ======================================================
                # VALIDAR UNIDAD
                # ======================================================

                unidad_valida = False

                # Misma unidad de consumo
                if unidad_entrada == unidad_consumo:
                    unidad_valida = True

                # Unidad de compra
                elif unidad_entrada == unidad_compra:
                    unidad_valida = True

                # Misma familia de unidades
                elif tipo_entrada == tipo_consumo:
                    unidad_valida = True

                if not unidad_valida:
                    raise ValueError(
                        f"No puedes registrar este material en "
                        f"{unidad['nombre']}. "
                        f"La unidad no es compatible con el material."
                    )

                # ======================================================
                # CONVERTIR A UNIDAD DE CONSUMO
                # ======================================================

                # ------------------------------------------------------
                # MISMA UNIDAD
                # ------------------------------------------------------

                if unidad_entrada == unidad_consumo:

                    cantidad_consumo = cantidad

                # ------------------------------------------------------
                # EJEMPLO:
                # 1 ft de vinil -> 30.48 cm
                #
                # ft y cm pertenecen a LONGITUD
                # ------------------------------------------------------

                elif tipo_entrada == tipo_consumo:

                    cantidad_consumo = (
                        cantidad
                        * factor_entrada
                        / factor_consumo
                    )

                # ------------------------------------------------------
                # EJEMPLO:
                # 1 paquete de papel -> 100 hojas
                # ------------------------------------------------------

                elif (
                    unidad_entrada == unidad_compra
                    and unidad_compra != unidad_consumo
                ):

                    cantidad_consumo = (
                        cantidad
                        * cantidad_por_compra
                    )

                else:

                    raise ValueError(
                        "No existe una conversión configurada "
                        "para esta unidad."
                    )

                # ======================================================
                # VALIDAR CONVERSIÓN
                # ======================================================

                if cantidad_consumo <= 0:
                    raise ValueError(
                        "La cantidad convertida debe ser mayor que cero."
                    )

                # ======================================================
                # COMPROBAR STOCK
                # ======================================================

                stock_actual = float(
                    material["stock_actual"]
                )

                if cantidad_consumo > stock_actual:
                    raise ValueError(
                        f"Stock insuficiente. "
                        f"Disponible: {stock_actual:.4f} "
                        f"{material['abreviatura_consumo']}. "
                        f"Solicitado: {cantidad_consumo:.4f} "
                        f"{material['abreviatura_consumo']}."
                    )

                # ======================================================
                # OBTENER LOTES
                #
                # FIFO:
                # primero se consume el lote más antiguo.
                # ======================================================

                cursor.execute("""
                    SELECT
                        id,
                        cantidad_actual,
                        costo_unitario
                    FROM lotes_inventario

                    WHERE material_id = %s
                      AND activo = 1
                      AND cantidad_actual > 0

                    ORDER BY id ASC

                    FOR UPDATE
                """, (material_id,))

                lotes = cursor.fetchall()

                cantidad_restante = cantidad_consumo
                costo_total_consumido = 0

                # ======================================================
                # CONSUMIR LOTES
                # ======================================================

                for lote in lotes:

                    if cantidad_restante <= 0.000001:
                        break

                    cantidad_lote = float(
                        lote["cantidad_actual"]
                    )

                    costo_unitario_lote = float(
                        lote["costo_unitario"]
                    )

                    cantidad_a_consumir = min(
                        cantidad_restante,
                        cantidad_lote
                    )

                    # Costo real del material utilizado
                    costo_consumido = (
                        cantidad_a_consumir
                        * costo_unitario_lote
                    )

                    costo_total_consumido += costo_consumido

                    nueva_cantidad_lote = (
                        cantidad_lote
                        - cantidad_a_consumir
                    )

                    # Actualizar lote
                    cursor.execute("""
                        UPDATE lotes_inventario
                        SET
                            cantidad_actual = %s,
                            activo = %s
                        WHERE id = %s
                    """, (
                        nueva_cantidad_lote,
                        1 if nueva_cantidad_lote > 0.000001 else 0,
                        lote["id"]
                    ))

                    cantidad_restante -= cantidad_a_consumir

                # ======================================================
                # VALIDAR LOTES
                # ======================================================

                if cantidad_restante > 0.000001:

                    raise ValueError(
                        "No existen lotes suficientes para "
                        "realizar este consumo."
                    )

                # ======================================================
                # NUEVO STOCK
                # ======================================================

                nuevo_stock = (
                    stock_actual - cantidad_consumo
                )

                # Evitar pequeños residuos por decimales
                if abs(nuevo_stock) < 0.000001:
                    nuevo_stock = 0

                cursor.execute("""
                    UPDATE materiales
                    SET
                        stock_actual = %s
                    WHERE id = %s
                """, (
                    nuevo_stock,
                    material_id
                ))

                # ======================================================
                # COSTO PROMEDIO REAL DEL CONSUMO
                # ======================================================

                costo_promedio = (
                    costo_total_consumido
                    / cantidad_consumo
                )

                # ======================================================
                # REGISTRAR MOVIMIENTO
                #
                # IMPORTANTE:
                # Se guarda en la unidad de CONSUMO.
                #
                # Para el vinil:
                # 1 pie -> 30.48 cm
                #
                # El movimiento guarda:
                # cantidad = 30.48
                # unidad = cm
                # costo_unitario = Q0.262467
                # ======================================================

                cursor.execute("""
                    INSERT INTO movimientos_inventario (
                        material_id,
                        variante_id,
                        tipo,
                        cantidad,
                        unidad_id,
                        costo_unitario,
                        referencia_tipo,
                        referencia_id,
                        usuario_id,
                        notas
                    )
                    VALUES (
                        %s,
                        NULL,
                        'CONSUMO',
                        %s,
                        %s,
                        %s,
                        'SALIDA_MANUAL',
                        NULL,
                        %s,
                        %s
                    )
                """, (
                    material_id,
                    cantidad_consumo,
                    unidad_consumo,
                    costo_promedio,
                    8,
                    notas
                ))

                # ======================================================
                # GUARDAR
                # ======================================================

                conn.commit()

                # ======================================================
                # MENSAJE
                # ======================================================

                flash(
                    f"Salida registrada: "
                    f"{cantidad:g} {unidad['abreviatura']} → "
                    f"{cantidad_consumo:.4f} "
                    f"{material['abreviatura_consumo']}. "
                    f"Costo consumido: "
                    f"Q{costo_total_consumido:.4f}. "
                    f"Stock restante: "
                    f"{nuevo_stock:.4f} "
                    f"{material['abreviatura_consumo']}.",
                    "success"
                )

                cursor.close()
                conn.close()

                return redirect(
                    url_for("inventario.lista")
                )

            except Exception as e:

                conn.rollback()

                flash(
                    f"No se pudo registrar la salida: {e}",
                    "danger"
                )

    # ==========================================================
    # MATERIALES DISPONIBLES
    # ==========================================================

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.stock_actual,

            m.unidad_compra_id,
            m.unidad_consumo_id,
            m.cantidad_por_compra,

            uc.nombre AS unidad_compra,
            uc.abreviatura AS abreviatura_compra,
            uc.tipo AS tipo_compra,

            ucons.nombre AS unidad_consumo,
            ucons.abreviatura AS abreviatura_consumo,
            ucons.tipo AS tipo_consumo

        FROM materiales m

        INNER JOIN unidades_medida uc
            ON m.unidad_compra_id = uc.id

        INNER JOIN unidades_medida ucons
            ON m.unidad_consumo_id = ucons.id

        WHERE m.activo = 1
          AND m.stock_actual > 0

        ORDER BY m.nombre ASC
    """)

    materiales = cursor.fetchall()

    # ==========================================================
    # TODAS LAS UNIDADES
    # ==========================================================

    cursor.execute("""
        SELECT
            id,
            nombre,
            abreviatura,
            tipo,
            factor_conversion
        FROM unidades_medida
        ORDER BY id ASC
    """)

    unidades = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "inventario/salida.html",
        materiales=materiales,
        unidades=unidades
    )


# ==========================================================
# HISTORIAL DE INVENTARIO POR MATERIAL
# ==========================================================

@inventario_bp.route("/<int:material_id>/historial")
def historial(material_id):

    filtro = request.args.get("tipo", "todos").strip().lower()

    filtros_validos = {
        "todos",
        "entradas",
        "salidas",
        "ajustes",
        "mermas"
    }

    if filtro not in filtros_validos:
        filtro = "todos"

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.stock_actual,
            m.stock_minimo,
            m.costo_compra_referencia,
            um.nombre AS unidad,
            um.abreviatura,
            c.nombre AS categoria
        FROM materiales m
        LEFT JOIN unidades_medida um
            ON m.unidad_consumo_id = um.id
        LEFT JOIN categorias c
            ON m.categoria_id = c.id
        WHERE m.id = %s
    """, (material_id,))

    material = cursor.fetchone()

    if not material:
        cursor.close()
        conn.close()
        flash("El material solicitado no existe.", "danger")
        return redirect(url_for("inventario.lista"))

    condiciones = ["mi.material_id = %s"]
    parametros = [material_id]

    if filtro == "entradas":
        condiciones.append("""
            mi.tipo IN (
                'COMPRA',
                'DEVOLUCION',
                'AJUSTE_ENTRADA'
            )
        """)
    elif filtro == "salidas":
        condiciones.append("""
            mi.tipo IN (
                'CONSUMO',
                'VENTA',
                'AJUSTE_SALIDA',
                'MERMA'
            )
        """)
    elif filtro == "ajustes":
        condiciones.append("""
            mi.tipo IN (
                'AJUSTE_ENTRADA',
                'AJUSTE_SALIDA'
            )
        """)
    elif filtro == "mermas":
        condiciones.append("mi.tipo = 'MERMA'")

    where_sql = "WHERE " + " AND ".join(condiciones)

    cursor.execute(
        f"""
        SELECT
            mi.id,
            mi.tipo,
            mi.cantidad,
            mi.costo_unitario,
            mi.referencia_tipo,
            mi.referencia_id,
            mi.usuario_id,
            mi.fecha,
            mi.notas,
            um.nombre AS unidad,
            um.abreviatura,
            u.nombre AS usuario_nombre
        FROM movimientos_inventario mi
        INNER JOIN unidades_medida um
            ON mi.unidad_id = um.id
        LEFT JOIN usuarios u
            ON mi.usuario_id = u.id
        {where_sql}
        ORDER BY mi.fecha DESC, mi.id DESC
        """,
        tuple(parametros)
    )

    movimientos = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(*) AS todos,
            SUM(CASE
                WHEN tipo IN ('COMPRA','DEVOLUCION','AJUSTE_ENTRADA')
                THEN 1 ELSE 0 END
            ) AS entradas,
            SUM(CASE
                WHEN tipo IN ('CONSUMO','VENTA','AJUSTE_SALIDA','MERMA')
                THEN 1 ELSE 0 END
            ) AS salidas,
            SUM(CASE
                WHEN tipo IN ('AJUSTE_ENTRADA','AJUSTE_SALIDA')
                THEN 1 ELSE 0 END
            ) AS ajustes,
            SUM(CASE
                WHEN tipo = 'MERMA'
                THEN 1 ELSE 0 END
            ) AS mermas
        FROM movimientos_inventario
        WHERE material_id = %s
    """, (material_id,))

    contadores = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "inventario/historial.html",
        material=material,
        movimientos=movimientos,
        filtro=filtro,
        contadores=contadores
    )


# ==========================================================
# UTILIDAD: CONSUMIR LOTES FIFO PARA AJUSTES
# ==========================================================

def _consumir_lotes_fifo(cursor, material_id, cantidad):

    cursor.execute("""
        SELECT
            id,
            cantidad_actual,
            costo_unitario
        FROM lotes_inventario
        WHERE material_id = %s
          AND activo = 1
          AND cantidad_actual > 0
        ORDER BY id ASC
        FOR UPDATE
    """, (material_id,))

    lotes = cursor.fetchall()
    cantidad_restante = Decimal(str(cantidad))
    costo_total = Decimal("0")
    tolerancia = Decimal("0.000001")

    for lote in lotes:
        if cantidad_restante <= tolerancia:
            break

        cantidad_lote = Decimal(str(lote["cantidad_actual"] or 0))
        costo_unitario = Decimal(str(lote["costo_unitario"] or 0))
        cantidad_consumida = min(cantidad_restante, cantidad_lote)
        costo_total += cantidad_consumida * costo_unitario
        nueva_cantidad = cantidad_lote - cantidad_consumida

        cursor.execute("""
            UPDATE lotes_inventario
            SET cantidad_actual = %s,
                activo = %s
            WHERE id = %s
        """, (
            nueva_cantidad,
            1 if nueva_cantidad > tolerancia else 0,
            lote["id"]
        ))

        cantidad_restante -= cantidad_consumida

    if cantidad_restante > tolerancia:
        raise ValueError(
            "No existen lotes suficientes para realizar este ajuste."
        )

    return costo_total


# ==========================================================
# AJUSTE MANUAL DE INVENTARIO
# ==========================================================

@inventario_bp.route("/<int:material_id>/ajuste", methods=["GET", "POST"])
def ajuste(material_id):

    conn = obtener_conexion()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            m.id,
            m.nombre,
            m.color,
            m.stock_actual,
            m.stock_minimo,
            m.costo_compra_referencia,
            m.unidad_consumo_id,
            um.nombre AS unidad,
            um.abreviatura
        FROM materiales m
        INNER JOIN unidades_medida um
            ON m.unidad_consumo_id = um.id
        WHERE m.id = %s
          AND m.activo = 1
        FOR UPDATE
    """, (material_id,))

    material = cursor.fetchone()

    if not material:
        cursor.close()
        conn.close()
        flash("El material solicitado no existe o está inactivo.", "danger")
        return redirect(url_for("inventario.lista"))

    if request.method == "POST":

        tipo_ajuste = request.form.get("tipo_ajuste", "").strip().lower()
        cantidad_texto = request.form.get("cantidad", "").strip()
        notas = request.form.get("notas", "").strip()
        tipos_validos = {"entrada", "salida", "merma"}

        try:
            if tipo_ajuste not in tipos_validos:
                raise ValueError("Selecciona un tipo de ajuste válido.")

            if not cantidad_texto:
                raise ValueError("Debes indicar la cantidad del ajuste.")

            cantidad = Decimal(cantidad_texto)

            if cantidad <= 0:
                raise ValueError("La cantidad debe ser mayor que cero.")

            if not notas:
                raise ValueError("Debes indicar el motivo del ajuste.")

            stock_actual = Decimal(str(material["stock_actual"] or 0))
            costo_referencia = Decimal(
                str(material["costo_compra_referencia"] or 0)
            )
            unidad_id = material["unidad_consumo_id"]

            if tipo_ajuste == "entrada":
                nuevo_stock = stock_actual + cantidad
                costo_unitario = costo_referencia
                costo_total = cantidad * costo_unitario

                cursor.execute("""
                    INSERT INTO lotes_inventario (
                        material_id,
                        variante_id,
                        compra_id,
                        detalle_compra_id,
                        cantidad_original,
                        cantidad_actual,
                        unidad_id,
                        ancho,
                        largo,
                        area_total,
                        area_disponible,
                        costo_total,
                        costo_unitario,
                        activo
                    )
                    VALUES (
                        %s,
                        NULL,
                        NULL,
                        NULL,
                        %s,
                        %s,
                        %s,
                        NULL,
                        NULL,
                        NULL,
                        NULL,
                        %s,
                        %s,
                        1
                    )
                """, (
                    material_id,
                    cantidad,
                    cantidad,
                    unidad_id,
                    costo_total,
                    costo_unitario
                ))

                tipo_movimiento = "AJUSTE_ENTRADA"

            else:
                if cantidad > stock_actual:
                    raise ValueError(
                        f"Stock insuficiente. Disponible: "
                        f"{stock_actual} {material['abreviatura']}."
                    )

                costo_total = _consumir_lotes_fifo(
                    cursor,
                    material_id,
                    cantidad
                )

                nuevo_stock = stock_actual - cantidad

                if abs(nuevo_stock) < Decimal("0.000001"):
                    nuevo_stock = Decimal("0")

                costo_unitario = (
                    costo_total / cantidad
                    if cantidad > 0
                    else Decimal("0")
                )

                tipo_movimiento = (
                    "MERMA"
                    if tipo_ajuste == "merma"
                    else "AJUSTE_SALIDA"
                )

            cursor.execute("""
                UPDATE materiales
                SET stock_actual = %s
                WHERE id = %s
            """, (nuevo_stock, material_id))

            cursor.execute("""
                INSERT INTO movimientos_inventario (
                    material_id,
                    variante_id,
                    tipo,
                    cantidad,
                    unidad_id,
                    costo_unitario,
                    referencia_tipo,
                    referencia_id,
                    usuario_id,
                    notas
                )
                VALUES (
                    %s,
                    NULL,
                    %s,
                    %s,
                    %s,
                    %s,
                    'AJUSTE_MANUAL',
                    NULL,
                    %s,
                    %s
                )
            """, (
                material_id,
                tipo_movimiento,
                cantidad,
                unidad_id,
                costo_unitario,
                8,
                notas
            ))

            conn.commit()

            flash(
                f"Ajuste registrado correctamente. "
                f"Nuevo stock: {nuevo_stock} {material['abreviatura']}.",
                "success"
            )

            cursor.close()
            conn.close()

            return redirect(
                url_for(
                    "inventario.historial",
                    material_id=material_id
                )
            )

        except Exception as e:
            conn.rollback()
            flash(f"No se pudo registrar el ajuste: {e}", "danger")

    cursor.close()
    conn.close()

    return render_template(
        "inventario/ajuste.html",
        material=material
    )